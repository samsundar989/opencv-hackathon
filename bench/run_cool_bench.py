"""One command: launch a short-lived Graviton bench instance, run both arms on it, fetch results, terminate.

    python bench/run_cool_bench.py --bucket <private bucket> --ami <COOL G5 AMI id> --cool-price <USD/h>

What it does (us-east-2, profile `riversight`):
  1. Refuses to start unless the D-0004 budget `riversight-monthly` exists.
  2. Uploads `git archive HEAD` and the bench pack (bench/make_pack.py; private, holds USGS frames) to
     s3://<bucket>/bench/<run>/ and makes presigned URLs. The instance needs no IAM role.
  3. Launches one instance (default m9g.large) from the COOL AMI: IMDSv2 required, shutdown = terminate,
     a watchdog `shutdown -h +<minutes>` in user data. The user-data script
       - arm A: the AMI's COOL Python venv (the newest python with a non-pip cv2 that has ALIKED);
       - arm B: a clean venv with pip `opencv-python-headless==5.0.0.93`;
     runs bench/cool_bench.py for each and PUTs results.tgz + the log back through presigned URLs.
  4. Waits for results, terminates the instance whatever happens, writes prices.json and spend.json,
     extracts to results/cool_bench/<run>/ and runs bench/compare_arms.py.

Cost: one m9g.large for about two hours plus the COOL fee, well under the $2 the slice allows.
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
BUDGET = "riversight-monthly"

USER_DATA = r"""#!/bin/bash
exec > /var/log/riversight-bench.log 2>&1
set -x
shutdown -h +{watchdog_min}
W=/opt/rsb; mkdir -p $W/pack $W/code $W/results; cd $W
curl -sfS "{code_url}" -o code.tgz && tar xzf code.tgz -C code
curl -sfS "{pack_url}" -o pack.tgz && tar xzf pack.tgz -C pack

# arm A: COOL. On the COOL AMI the only preinstalled cv2 is COOL's: take the newest python >= 3.12 whose cv2
# imports and has ALIKED (--cool-python overrides). provenance.json records the cv2 path and build hash.
COOL_PY="{cool_python}"
if [ -z "$COOL_PY" ]; then
  for py in $(ls -d /opt/*/bin/python3.1? /opt/*/*/bin/python3.1? /opt/*/*/*/bin/python3.1? /home/*/*/bin/python3.1? /usr/local/bin/python3.1? 2>/dev/null | sort -V); do
    r=$($py -c "import sys,cv2;print(sys.version_info[:2]>=(3,12) and hasattr(cv2,'ALIKED'), cv2.__file__)" 2>/dev/null)
    echo "candidate $py -> $r"
    case "$r" in True*) COOL_PY=$py;; esac
  done
fi
echo "COOL_PY=$COOL_PY" | tee $W/results/arms.txt
if [ -n "$COOL_PY" ]; then
  $COOL_PY -m pip freeze > $W/results/cool_freeze.txt 2>&1
  $COOL_PY code/bench/cool_bench.py --pack $W/pack --out $W/results --arm cool {bench_args} || echo "cool arm failed" >> $W/results/arms.txt
fi

# arm B: stock pip OpenCV 5.0.0.93 in a clean venv on the same interpreter version where possible.
BASE=$($COOL_PY -c "import sys;print(sys._base_executable)" 2>/dev/null || echo python3)
$BASE -m venv /opt/pipvenv || python3 -m venv /opt/pipvenv
/opt/pipvenv/bin/pip install -q "opencv-python-headless==5.0.0.93" "numpy<3"
/opt/pipvenv/bin/pip freeze > $W/results/pip_freeze.txt
/opt/pipvenv/bin/python code/bench/cool_bench.py --pack $W/pack --out $W/results --arm pip-5.0.0.93 {bench_args} || echo "pip arm failed" >> $W/results/arms.txt

cp /var/log/riversight-bench.log $W/results/ || true
tar czf results.tgz results
curl -sfS -X PUT --upload-file results.tgz "{results_url}"
curl -sfS -X PUT --upload-file /var/log/riversight-bench.log "{log_url}"
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--ami", required=True, help="COOL G5 AMI id in us-east-2 (after the Marketplace subscription)")
    ap.add_argument("--instance-type", default="m9g.large")
    ap.add_argument("--cool-price", type=float, required=True, help="COOL software fee, USD/h, from the listing")
    ap.add_argument("--ec2-price", type=float, help="override the Price List lookup, USD/h")
    ap.add_argument("--pack", type=Path, default=ROOT / "data" / "bench_pack")
    ap.add_argument("--run", default=datetime.now(timezone.utc).strftime("aws_%Y-%m-%d"))
    ap.add_argument("--bench-args", default="--threads 1,all --dnn-iters 100 --fleet 20,880")
    ap.add_argument("--cool-python", default="", help="path of the COOL venv python on the AMI, if known")
    ap.add_argument("--watchdog-min", type=int, default=180)
    ap.add_argument("--profile", default="riversight")
    ap.add_argument("--dry-run", action="store_true", help="print the user data and stop before any AWS call")
    args = ap.parse_args()

    import boto3
    sess = boto3.Session(profile_name=args.profile, region_name=REGION)
    if args.dry_run:
        print(USER_DATA.format(watchdog_min=args.watchdog_min, code_url="<code>", pack_url="<pack>",
                               results_url="<results>", log_url="<log>", bench_args=args.bench_args,
                               cool_python=args.cool_python))
        return

    acct = sess.client("sts").get_caller_identity()["Account"]
    try:
        sess.client("budgets").describe_budget(AccountId=acct, BudgetName=BUDGET)
    except Exception as e:   # noqa: BLE001
        sys.exit(f"D-0004 guard: budget {BUDGET!r} not found ({e}). W1 creates it before any EC2 launch.")

    ec2_usd = args.ec2_price or ec2_price(sess, args.instance_type)
    if ec2_usd is None:
        sys.exit("no EC2 price; pass --ec2-price")

    s3 = sess.client("s3")
    prefix = f"bench/{args.run}"
    print("uploading code and pack ...")
    s3.put_object(Bucket=args.bucket, Key=f"{prefix}/code.tgz", Body=git_archive())
    s3.put_object(Bucket=args.bucket, Key=f"{prefix}/pack.tgz", Body=tar_dir(args.pack))
    ttl = 6 * 3600
    url = lambda op, key: s3.generate_presigned_url(op, Params={"Bucket": args.bucket, "Key": f"{prefix}/{key}"},  # noqa: E731
                                                     ExpiresIn=ttl)
    ud = USER_DATA.format(watchdog_min=args.watchdog_min, code_url=url("get_object", "code.tgz"),
                          pack_url=url("get_object", "pack.tgz"), results_url=url("put_object", "results.tgz"),
                          log_url=url("put_object", "bench.log"), bench_args=args.bench_args,
                          cool_python=args.cool_python)

    ec2 = sess.client("ec2")
    r = ec2.run_instances(
        ImageId=args.ami, InstanceType=args.instance_type, MinCount=1, MaxCount=1, UserData=ud,
        InstanceInitiatedShutdownBehavior="terminate",
        MetadataOptions={"HttpTokens": "required", "HttpEndpoint": "enabled"},
        TagSpecifications=[{"ResourceType": "instance", "Tags": [
            {"Key": "Project", "Value": "riversight"}, {"Key": "Purpose", "Value": "cool-bench"},
            {"Key": "Name", "Value": f"riversight-cool-bench-{args.run}"}]}])
    iid = r["Instances"][0]["InstanceId"]
    t0 = time.time()
    print(f"launched {iid} ({args.instance_type}, {args.ami}); waiting for results (watchdog {args.watchdog_min} min)")
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
        print(f"terminated {iid} after {hours:.2f} h")

    out = ROOT / "results" / "cool_bench" / args.run
    out.mkdir(parents=True, exist_ok=True)
    try:
        body = s3.get_object(Bucket=args.bucket, Key=f"{prefix}/results.tgz")["Body"].read()
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as t:
            for m in t.getmembers():
                rel = Path(m.name).relative_to("results") if m.name.startswith("results") else None
                if rel is None or not m.isfile() or ".." in rel.parts:
                    continue
                dst = out / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(t.extractfile(m).read())
    except s3.exceptions.NoSuchKey:
        try:
            (out / "bench.log").write_bytes(s3.get_object(Bucket=args.bucket, Key=f"{prefix}/bench.log")["Body"].read())
        except s3.exceptions.NoSuchKey:
            pass
        sys.exit(f"no results.tgz; see {out / 'bench.log'} if it exists")

    prices = {"instance": args.instance_type, "ec2_usd_per_h": ec2_usd, "cool_usd_per_h": args.cool_price,
              "region": REGION, "source": "ec2: AWS Price List API (or --ec2-price); cool: Marketplace listing",
              "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    (out / "prices.json").write_text(json.dumps(prices, indent=1), encoding="utf-8")
    (out / "spend.json").write_text(json.dumps({"instance_id": iid, "ami": args.ami, "hours": round(hours, 3),
                                                "usd_estimate": round(hours * (ec2_usd + args.cool_price), 4)},
                                               indent=1), encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "bench" / "compare_arms.py"), str(out), "--baseline", "pip-5.0.0.93"],
                   check=False)
    print(f"results in {out}")


if __name__ == "__main__":
    main()
