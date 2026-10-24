"""One command: launch a short-lived Graviton bench instance, run both arms on it, fetch results, terminate.

    python bench/run_cool_bench.py --bucket <private bucket> --ami <COOL G5 AMI id> --cool-price <USD/h>

What it does (us-east-2, profile `riversight`):
  1. Refuses to start unless the D-0004 budget `riversight-cap` (W1 GuardStack) exists.
  2. Uploads `git archive HEAD` and the bench pack (bench/make_pack.py; private, holds USGS frames) to
     s3://<bucket>/bench/<run>/. Ensures a minimal instance role `riversight-cool-bench` that can only read
     and write `bench/*` in that bucket (presigned URLs would die with the caller's short session).
  3. Launches one instance (default m9g.large) from the COOL AMI: IMDSv2 required, shutdown = terminate,
     a watchdog `shutdown -h +<minutes>` in user data. The user-data script
       - arm A: the AMI's COOL Python venv (the newest python with a non-pip cv2 that has ALIKED);
       - arm B: a clean venv with pip `opencv-python-headless==5.0.0.93`;
     runs bench/cool_bench.py for each and uploads results.tgz + the log to bench/<run>/.
  4. Waits for results, terminates the instance whatever happens, writes prices.json and spend.json,
     extracts to results/cool_bench/<run>/ and runs bench/compare_arms.py.

If the waiting process dies, the instance still terminates itself (finish or watchdog). Then
    python bench/run_cool_bench.py --bucket <bucket> --collect --run <run> --ami <ami> --cool-price <USD/h>
fetches the results, terminates any leftover bench instance and writes the comparison.

Cost: one m9g.large for a few hours plus the COOL fee, under the $2 the slice allows.
"""
from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGION = "us-east-2"
BUDGET = "riversight-cap"     # W1 GuardStack (D-0004); its 90 % action stops instances tagged Project=riversight
UBUNTU_ARM64 = "/aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id"

USER_DATA = r"""#!/bin/bash
exec > /var/log/riversight-bench.log 2>&1
set -x
shutdown -h +{watchdog_min}
W=/opt/rsb; mkdir -p $W/pack $W/code $W/results; cd $W
# S3 transfer through the instance role (boto3 in its own small venv)
python3 -m venv /opt/xfer || {{
  apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3-venv && python3 -m venv /opt/xfer; }}
/opt/xfer/bin/pip install -q boto3
cat > /opt/xfer/x.py <<'PYX'
import sys
import boto3
s3 = boto3.client("s3", region_name="us-east-2")
op, a, b = sys.argv[1:4]
if op == "get":
    s3.download_file("{bucket}", "{prefix}/" + a, b)
else:
    s3.upload_file(a, "{bucket}", "{prefix}/" + b)
PYX
X="/opt/xfer/bin/python /opt/xfer/x.py"
$X get code.tgz code.tgz && tar xzf code.tgz -C code
$X get pack.tgz pack.tgz && tar xzf pack.tgz -C pack

# arm A: COOL, set up exactly like the live worker (infra/worker/bootstrap.sh) and COOL's own activate script:
# the newest /usr/bin/python3.X that has a COOL cv2 under /opt/cool, a venv on it with COOL's numpy version,
# cv2 from /opt/cool via PYTHONPATH, the COOL C++ SDK and FFmpeg via LD_LIBRARY_PATH.
SKIP_COOL="{skip_cool}"      # 1 on the stock-Ubuntu fallback (D-0009): no COOL arm at all
CV=""; NUMPY_V=""
for v in 3.14 3.13 3.12; do
  if [ -d "/opt/cool/python_$v/site-packages/cv2/python-$v" ] && [ -x "/usr/bin/python$v" ]; then CV=$v; break; fi
done
echo "COOL python: $CV" | tee $W/results/arms.txt
ls -d /opt/cool/* >> $W/results/arms.txt 2>&1
if [ "$SKIP_COOL" != "1" ] && [ -n "$CV" ]; then
  NUMPY_V=$(ls -d /opt/cool/python_$CV/site-packages/numpy-*.dist-info | sed -E 's/.*numpy-([^-]+)\.dist-info/\1/' | head -1)
  /usr/bin/python$CV -m venv /opt/coolvenv
  /opt/coolvenv/bin/pip install -q "numpy==$NUMPY_V"
  /opt/coolvenv/bin/pip freeze > $W/results/cool_freeze.txt
  PYTHONPATH="/opt/cool/python_$CV/site-packages/cv2/python-$CV" LD_LIBRARY_PATH="/opt/cool/cpp_sdk/lib:/opt/ffmpeg/lib" \
    /opt/coolvenv/bin/python code/bench/cool_bench.py --pack $W/pack --out $W/results --arm cool {bench_args} \
    || echo "cool arm failed" >> $W/results/arms.txt
fi

# arm B: stock pip OpenCV 5.0.0.93 in a clean venv on the same interpreter, with the same numpy as arm A,
# so OpenCV is the only difference between the arms.
BASE=/usr/bin/python$CV; [ -x "$BASE" ] || BASE=python3
$BASE -m venv /opt/pipvenv || {{
  # stock Ubuntu ships python3 without ensurepip
  apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3-venv && python3 -m venv /opt/pipvenv; }}
if [ -n "$NUMPY_V" ]; then NP="numpy==$NUMPY_V"; else NP="numpy<3"; fi
/opt/pipvenv/bin/pip install -q "opencv-python-headless==5.0.0.93" "$NP"
/opt/pipvenv/bin/pip freeze > $W/results/pip_freeze.txt
/opt/pipvenv/bin/python code/bench/cool_bench.py --pack $W/pack --out $W/results --arm pip-5.0.0.93 {bench_args} || echo "pip arm failed" >> $W/results/arms.txt

cp /var/log/riversight-bench.log $W/results/ || true
tar czf results.tgz results
$X put results.tgz results.tgz
$X put /var/log/riversight-bench.log bench.log
shutdown -h now
"""


def git_archive() -> bytes:
    return subprocess.run(["git", "archive", "--format=tar.gz", "HEAD"], cwd=ROOT, check=True,
                          capture_output=True).stdout


def tar_dir(d: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for p in sorted(d.rglob("*")):
            if p.is_file():
                t.add(p, arcname=str(p.relative_to(d)).replace("\\", "/"))
    return buf.getvalue()


def ec2_price(sess, instance_type: str) -> float | None:
    """On-demand Linux price from the AWS Price List API (its endpoint is us-east-1; read-only)."""
    try:
        pr = sess.client("pricing", region_name="us-east-1")
        flt = [{"Type": "TERM_MATCH", "Field": k, "Value": v} for k, v in {
            "instanceType": instance_type, "regionCode": REGION, "operatingSystem": "Linux", "tenancy": "Shared",
            "preInstalledSw": "NA", "capacitystatus": "Used"}.items()]
        item = json.loads(pr.get_products(ServiceCode="AmazonEC2", Filters=flt, MaxResults=1)["PriceList"][0])
        term = next(iter(item["terms"]["OnDemand"].values()))
        return float(next(iter(term["priceDimensions"].values()))["pricePerUnit"]["USD"])
    except Exception as e:   # noqa: BLE001
        print(f"price lookup failed ({e}); pass --ec2-price")
        return None


ROLE = "riversight-cool-bench"


def ensure_bench_role(sess, bucket: str) -> str:
    """Instance role + profile that can only get/put bench/* in the bucket. Idempotent; returns the profile name."""
    iam = sess.client("iam")
    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"},
                                                      "Action": "sts:AssumeRole"}]}
    policy = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"],
                                                       "Resource": f"arn:aws:s3:::{bucket}/bench/*"}]}
    created = False
    try:
        iam.get_role(RoleName=ROLE)
    except iam.exceptions.NoSuchEntityException:
        iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust),
                        Description="RiverSight COOL bench: read/write bench/* only",
                        Tags=[{"Key": "Project", "Value": "riversight"}])
        created = True
    iam.put_role_policy(RoleName=ROLE, PolicyName="bench-s3", PolicyDocument=json.dumps(policy))
    try:
        iam.get_instance_profile(InstanceProfileName=ROLE)
    except iam.exceptions.NoSuchEntityException:
        iam.create_instance_profile(InstanceProfileName=ROLE)
        created = True
    if not iam.get_instance_profile(InstanceProfileName=ROLE)["InstanceProfile"]["Roles"]:
        iam.add_role_to_instance_profile(InstanceProfileName=ROLE, RoleName=ROLE)
        created = True
    if created:
        time.sleep(15)   # IAM propagation before EC2 can use the profile
    return ROLE


def collect(sess, bucket: str, out: Path, prefix: str) -> bool:
    """Fetch results.tgz (or only the log) from S3 into out/. True when results arrived."""
    s3 = sess.client("s3")
    out.mkdir(parents=True, exist_ok=True)
    try:
        body = s3.get_object(Bucket=bucket, Key=f"{prefix}/results.tgz")["Body"].read()
    except s3.exceptions.NoSuchKey:
        try:
            (out / "bench.log").write_bytes(s3.get_object(Bucket=bucket, Key=f"{prefix}/bench.log")["Body"].read())
        except s3.exceptions.NoSuchKey:
            pass
        return False
    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as t:
        for m in t.getmembers():
            rel = Path(m.name).relative_to("results") if m.name.startswith("results") else None
            if rel is None or not m.isfile() or ".." in rel.parts:
                continue
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(t.extractfile(m).read())
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--ami", help="COOL G5 AMI id in us-east-2 (after the Marketplace subscription)")
    ap.add_argument("--stock", action="store_true",
                    help="D-0009 fallback: stock Ubuntu 24.04 arm64, pip arm only (Graviton vs the x86 dev box); COOL not run")
    ap.add_argument("--instance-type", default="m9g.large")
    ap.add_argument("--cool-price", type=float, default=0.0, help="COOL software fee, USD/h, from the listing")
    ap.add_argument("--ec2-price", type=float, help="override the Price List lookup, USD/h")
    ap.add_argument("--pack", type=Path, default=ROOT / "data" / "bench_pack")
    ap.add_argument("--run", default=datetime.now(timezone.utc).strftime("aws_%Y-%m-%d"))
    ap.add_argument("--bench-args", default="--threads 1,all --dnn-iters 100 --fleet 20,880")
    ap.add_argument("--watchdog-min", type=int, default=330)
    ap.add_argument("--collect", action="store_true", help="only fetch the results of --run and terminate leftovers")
    ap.add_argument("--profile", default="riversight")
    ap.add_argument("--dry-run", action="store_true", help="print the user data and stop before any AWS call")
    args = ap.parse_args()

    if not args.stock and (not args.ami or args.cool_price <= 0):
        ap.error("the COOL run needs --ami and --cool-price (or pass --stock for the D-0009 fallback)")
    skip_cool = "1" if args.stock else ""

    import boto3
    sess = boto3.Session(profile_name=args.profile, region_name=REGION)
    if args.dry_run:
        print(USER_DATA.format(watchdog_min=args.watchdog_min, bucket=args.bucket, prefix=f"bench/{args.run}",
                               bench_args=args.bench_args, skip_cool=skip_cool))
        return
    if args.stock:
        args.ami = sess.client("ssm").get_parameter(Name=UBUNTU_ARM64)["Parameter"]["Value"]
        args.cool_price = 0.0

    acct = sess.client("sts").get_caller_identity()["Account"]
    try:
        sess.client("budgets").describe_budget(AccountId=acct, BudgetName=BUDGET)
    except Exception as e:   # noqa: BLE001
        sys.exit(f"D-0004 guard: budget {BUDGET!r} not found ({e}). W1 creates it before any EC2 launch.")

    ec2_usd = args.ec2_price or ec2_price(sess, args.instance_type)
    if ec2_usd is None:
        sys.exit("no EC2 price; pass --ec2-price")

    s3 = sess.client("s3")
    ec2 = sess.client("ec2")
    prefix = f"bench/{args.run}"
    out = ROOT / "results" / "cool_bench" / args.run
    tag = f"riversight-cool-bench-{args.run}"
    iid, hours = None, None

    if args.collect:
        left = [i["InstanceId"] for r in ec2.describe_instances(Filters=[
            {"Name": "tag:Name", "Values": [tag]},
            {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}])["Reservations"]
            for i in r["Instances"]]
        if left:
            ec2.terminate_instances(InstanceIds=left)
            print(f"terminated leftover {left}")
    else:
        profile = ensure_bench_role(sess, args.bucket)
        print("uploading code and pack ...", flush=True)
        s3.put_object(Bucket=args.bucket, Key=f"{prefix}/code.tgz", Body=git_archive())
        s3.put_object(Bucket=args.bucket, Key=f"{prefix}/pack.tgz", Body=tar_dir(args.pack))
        ud = USER_DATA.format(watchdog_min=args.watchdog_min, bucket=args.bucket, prefix=prefix,
                              bench_args=args.bench_args, skip_cool=skip_cool)
        for attempt in range(6):
            try:
                r = ec2.run_instances(
                    ImageId=args.ami, InstanceType=args.instance_type, MinCount=1, MaxCount=1, UserData=ud,
                    IamInstanceProfile={"Name": profile},
                    InstanceInitiatedShutdownBehavior="terminate",
                    MetadataOptions={"HttpTokens": "required", "HttpEndpoint": "enabled"},
                    TagSpecifications=[{"ResourceType": "instance", "Tags": [
                        {"Key": "Project", "Value": "riversight"}, {"Key": "Purpose", "Value": "cool-bench"},
                        {"Key": "Name", "Value": tag}]}])
                break
            except ec2.exceptions.ClientError as e:
                if "iamInstanceProfile" not in str(e) or attempt == 5:
                    raise
                time.sleep(10)          # instance profile not visible to EC2 yet
        iid = r["Instances"][0]["InstanceId"]
        t0 = time.time()
        print(f"launched {iid} ({args.instance_type}, {args.ami}); waiting for results "
              f"(watchdog {args.watchdog_min} min)", flush=True)
        try:
            deadline = t0 + args.watchdog_min * 60 + 600
            while time.time() < deadline:
                try:
                    s3.head_object(Bucket=args.bucket, Key=f"{prefix}/results.tgz")
                    break
                except s3.exceptions.ClientError:
                    time.sleep(60)
                    print(f"  {int((time.time() - t0) / 60)} min ...", flush=True)
            else:
                print("timed out waiting for results")
        finally:
            ec2.terminate_instances(InstanceIds=[iid])
            hours = (time.time() - t0) / 3600
            print(f"terminated {iid} after {hours:.2f} h", flush=True)

    if not collect(sess, args.bucket, out, prefix):
        sys.exit(f"no results.tgz yet; see {out / 'bench.log'} if it exists")

    prices = {"instance": args.instance_type, "ec2_usd_per_h": ec2_usd, "cool_usd_per_h": args.cool_price,
              "region": REGION, "source": "ec2: AWS Price List API (or --ec2-price); cool: Marketplace listing",
              "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    (out / "prices.json").write_text(json.dumps(prices, indent=1), encoding="utf-8")
    if hours is not None:
        (out / "spend.json").write_text(json.dumps({"instance_id": iid, "ami": args.ami, "hours": round(hours, 3),
                                                    "usd_estimate": round(hours * (ec2_usd + args.cool_price), 4)},
                                                   indent=1), encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "bench" / "compare_arms.py"), str(out), "--baseline", "pip-5.0.0.93"],
                   check=False)
    print(f"results in {out}")


if __name__ == "__main__":
    main()
