#!/bin/bash
# RiverSight Graviton worker bootstrap (EC2 user data; placeholders filled by infra/stacks/live.py).
# Installs the runtime, pulls the deploy tarball from S3, and runs the live cycle every 15 min from a
# systemd timer (each site is processed every 30 min, or every 15 min while the agent has it DENSIFY'd).
set -euxo pipefail
exec > >(tee -a /var/log/riversight-bootstrap.log) 2>&1

BUCKET="__BUCKET__"
REGION="__REGION__"
AMI_KIND="__AMI_KIND__"
mkdir -p /opt/riversight /var/cache/riversight

if [ "$AMI_KIND" = "cool" ]; then
  # COOL G5 AMI (Python 3.12-3.14 bindings): find the newest interpreter whose cv2 imports, then build a
  # --system-site-packages venv on it so our deps install without shadowing COOL's cv2 or its numpy.
  echo "== COOL discovery =="; ls -la /opt 2>/dev/null || true
  find / -xdev \( -path /proc -o -path /sys \) -prune -o -name "cv2*.so" -print 2>/dev/null | head -20 || true
  BASE=""
  for c in $(find / -xdev \( -path /proc -o -path /sys -o -path /snap \) -prune -o -type f -name 'python3.1[234]' -perm -u+x -print 2>/dev/null | sort -rV); do
    if "$c" -c "import cv2; print('cv2', cv2.__version__, cv2.__file__)" 2>/dev/null; then BASE="$c"; break; fi
  done
  [ -n "$BASE" ] || { echo "no COOL python with cv2 found"; exit 1; }
  echo "COOL python: $BASE"
  "$BASE" -m venv --system-site-packages /opt/riversight/venv || { "$BASE" -m ensurepip || true; "$BASE" -m venv --system-site-packages --without-pip /opt/riversight/venv; }
  PY=/opt/riversight/venv/bin/python
  "$PY" -m ensurepip 2>/dev/null || true
  "$PY" -m pip install pandas pyarrow scipy httpx pyyaml tenacity boto3
  "$PY" -c "import cv2, numpy; print('venv cv2', cv2.__version__, cv2.__file__, 'numpy', numpy.__version__)"
  if "$PY" -m pip show opencv-python-headless >/dev/null 2>&1; then echo "pip opencv shadows COOL: removing"; "$PY" -m pip uninstall -y opencv-python-headless; fi
else
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y python3-venv python3-pip
  python3 -m venv /opt/riversight/venv
  PY=/opt/riversight/venv/bin/python
  "$PY" -m pip install -U pip
  "$PY" -m pip install "opencv-python-headless==5.0.0.93" "numpy>=2,<3" pandas pyarrow scipy httpx pyyaml \
      tenacity boto3
fi
echo "$PY" > /opt/riversight/python

cat > /opt/riversight/update.sh <<EOF
#!/bin/bash
# Pull the newest deploy tarball (scripts/deploy.py uploads it) and swap it in atomically.
set -euo pipefail
"$PY" - <<'PYEOF'
import boto3, tarfile, shutil, pathlib
root = pathlib.Path("/opt/riversight")
tmp = root / "app.new"
shutil.rmtree(tmp, ignore_errors=True)
tmp.mkdir()
boto3.client("s3", region_name="$REGION").download_file("$BUCKET", "deploy/riversight.tar.gz", "/tmp/riversight.tar.gz")
with tarfile.open("/tmp/riversight.tar.gz") as t:
    t.extractall(tmp, filter="data")
old = root / "app"
if old.exists():
    shutil.rmtree(root / "app.old", ignore_errors=True)
    old.rename(root / "app.old")
tmp.rename(old)
PYEOF
EOF
chmod +x /opt/riversight/update.sh

cat > /opt/riversight/env <<EOF
AWS_DEFAULT_REGION=$REGION
RIVERSIGHT_BUCKET=$BUCKET
PYTHONPATH=/opt/riversight/app/src
RIVERSIGHT_BUNDLES=/opt/riversight/app/models/sites
RIVERSIGHT_MODELS=/opt/riversight/app/models/onnx
RIVERSIGHT_FRAME_CACHE=/var/cache/riversight
RIVERSIGHT_SNS_TOPIC=__ALERTS__
RIVERSIGHT_SITE_URL=__SITE_URL__
RIVERSIGHT_METRICS=1
RIVERSIGHT_AMI_KIND=$AMI_KIND
OPENBLAS_NUM_THREADS=1
EOF

cat > /etc/systemd/system/riversight-cycle.service <<EOF
[Unit]
Description=RiverSight live cycle (one pass over all sites)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
EnvironmentFile=/opt/riversight/env
ExecStartPre=/usr/bin/find /var/cache/riversight -type f -mtime +2 -delete
ExecStart=/bin/bash -c 'RIVERSIGHT_CODE_SHA=\$(cat /opt/riversight/app/CODE_SHA 2>/dev/null || echo unknown) exec $PY -m riversight.live.cycle --s3 $BUCKET'
TimeoutStartSec=840
MemoryMax=80%
Nice=5
EOF

cat > /etc/systemd/system/riversight-cycle.timer <<EOF
[Unit]
Description=Run the RiverSight live cycle every 15 minutes

[Timer]
OnCalendar=*:2/15
Persistent=true
RandomizedDelaySec=30

[Install]
WantedBy=timers.target
EOF

# the tarball may not be uploaded yet on first boot: retry for up to 30 min
for i in $(seq 1 60); do
  if /opt/riversight/update.sh; then break; fi
  sleep 30
done
systemctl daemon-reload
systemctl enable --now riversight-cycle.timer
systemctl start riversight-cycle.service || true
