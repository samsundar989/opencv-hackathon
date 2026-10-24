"""One-command deploy (SPRINT W1 step 3): guard → live stack → tarball + site upload → worker update → smoke test.

  python scripts/deploy.py                 full deploy (prints the URL and the wall time)
  python scripts/deploy.py --guard-only    only the D-0004 budget guard (run and verify before any EC2 launch)
  python scripts/deploy.py --site-only     only re-upload web/ + site data and invalidate CloudFront
  python scripts/deploy.py --code-only     only re-upload the worker tarball and tell the worker to update

Credentials: `aws login --profile riversight` (override with --profile / AWS_PROFILE). Region us-east-2 only.
The approval token is generated once into .env (gitignored, APPROVAL_TOKEN=...); only its sha256 goes into
the stack, and the token is emailed to the alert topic's subscriber (Samuel) the first time.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import mimetypes
import os
import secrets
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
INFRA = ROOT / "infra"
OUTPUTS = INFRA / "cdk-outputs.json"
REGION = "us-east-2"
ONNX = ("aliked-n16rot-top1k-640.onnx", "aliked_lightglue.onnx", "face_detection_yunet_2023mar.onnx")


def sh(cmd: list[str], **kw) -> str:
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, text=True, **kw).stdout or ""


def cdk(args: list[str], profile: str, ctx: dict | None = None):
    c = ["cdk", *args, "--profile", profile, "--require-approval", "never"]
    for k, v in (ctx or {}).items():
        c += ["-c", f"{k}={v}"]
    sh(c if os.name != "nt" else ["cmd", "/c", *c], cwd=INFRA)


def session(profile: str):
    import boto3
    return boto3.Session(profile_name=profile, region_name=REGION)


def git_sha() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def env_secret(name: str) -> tuple[str, bool]:
    """A secret kept only in the gitignored .env (generated on first use). Returns (value, newly created)."""
    env = ROOT / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    for ln in lines:
        if ln.startswith(f"{name}="):
            return ln.split("=", 1)[1].strip(), False
    tok = secrets.token_urlsafe(24)
    with env.open("a", encoding="utf-8") as f:
        f.write(f"\n{name}={tok}\n")
    return tok, True


def approval_token() -> tuple[str, bool]:
    return env_secret("APPROVAL_TOKEN")


def outputs() -> dict:
    d = json.loads(OUTPUTS.read_text(encoding="utf-8"))
    return {**d.get("RiverSightGuard", {}), **d.get("RiverSightLive", {})}


def verify_guard(sess) -> dict:
    acct = sess.client("sts").get_caller_identity()["Account"]
    b = sess.client("budgets").describe_budget(AccountId=acct, BudgetName="riversight-cap")["Budget"]
    notes = sess.client("budgets").describe_notifications_for_budget(AccountId=acct, BudgetName="riversight-cap")
    out = {"budget_arn": f"arn:aws:budgets::{acct}:budget/riversight-cap",
           "limit": b["BudgetLimit"], "actual": b.get("CalculatedSpend", {}).get("ActualSpend"),
           "forecast": b.get("CalculatedSpend", {}).get("ForecastedSpend"),
           "notifications": [(n["NotificationType"], n["Threshold"]) for n in notes["Notifications"]]}
    print(json.dumps(out, indent=2, default=str))
    return out


def tarball() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        def add(p: Path, arc: str):
            t.add(p, arcname=arc, filter=lambda ti: None if "__pycache__" in ti.name or ti.name.endswith(".pyc") else ti)
        # code from the committed HEAD, never the shared working tree (other workers' uncommitted edits)
        code = subprocess.run(["git", "archive", "--format=tar", "HEAD", "src/riversight"], cwd=ROOT,
                              capture_output=True, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(code)) as src:
            for m in src.getmembers():
                if "__pycache__" not in m.name:
                    t.addfile(m, src.extractfile(m) if m.isfile() else None)
        add(ROOT / "models" / "sites", "models/sites")
        for f in ONNX:
            add(ROOT / "models" / "onnx" / f, f"models/onnx/{f}")
        add(ROOT / "results" / "live_prospective" / "frozen_models.json", "results/live_prospective/frozen_models.json")
        if (ROOT / "models" / "sites_v2").is_dir():          # W4 shadow model (D-0010 §2): bundles + DINOv2 net
            add(ROOT / "models" / "sites_v2", "models/sites_v2")
            add(ROOT / "models" / "onnx" / "dinov2_small_224x392.onnx", "models/onnx/dinov2_small_224x392.onnx")
        sha = git_sha().encode()
        ti = tarfile.TarInfo("CODE_SHA")
        ti.size = len(sha)
        t.addfile(ti, io.BytesIO(sha))
    return buf.getvalue()


def upload_code(sess, bucket: str):
    data = tarball()
    print(f"tarball {len(data) / 1e6:.1f} MB", flush=True)
    sess.client("s3").put_object(Bucket=bucket, Key="deploy/riversight.tar.gz", Body=data)


def site_data() -> dict[str, bytes]:
    """Judge/site data files built from committed results (no numbers typed by hand)."""
    import pandas as pd
    out: dict[str, bytes] = {}
    kt = ROOT / "results" / "kill_test_v2.csv"
    if kt.exists():
        df = pd.read_csv(kt)
        out["data/kill_test_v2.json"] = df.to_json(orient="records").encode()
    for v in sorted((ROOT / "results").glob("kill_test_v2_*.json")):
        out[f"data/{v.name}"] = v.read_bytes()
    for v in sorted((ROOT / "results" / "agent_eval" / "replay").glob("*")):
        if v.suffix in (".png", ".jpg"):
            out[f"agent_replay/{v.name}"] = v.read_bytes()
    for v in sorted((ROOT / "results" / "demo").glob("*")):
        out[f"demo/{v.name}"] = v.read_bytes()
    for extra in ("results/agent_eval/summary.json", "results/cool_bench/summary.json", "results/fleet_summary.json"):
        p = ROOT / extra
        if p.exists():
            out[f"data/{Path(extra).parent.name}_{p.name}"] = p.read_bytes()
    sites = []
    for d in sorted((ROOT / "models" / "sites").iterdir()):
        if not (d / "meta.json").exists() or d.name.startswith("."):
            continue
        m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        keep = {k: m[k] for k in ("cam_id", "nwis_id", "lat", "lon", "state", "tier", "sigma_ft", "calib_start",
                                  "calib_end", "n_calib_frames", "stage_p05", "stage_p50", "stage_p90", "stage_p95",
                                  "stage_min", "stage_max", "flood_elevated_ft", "flood_ft", "n_roi_blocks",
                                  "ref_shape", "model_sha", "trained_at", "label")}
        keep["extra_references"] = [{k: e[k] for k in ("file", "start", "end", "linked")} for e in m["extra_references"]]
        sites.append(keep)
        hs = json.loads((d / "hstar.json").read_text(encoding="utf-8"))
        from riversight.live.bundle import SiteModel
        hs["seed"] = [int(i) for i in SiteModel(d).seed().ravel().nonzero()[0]]   # connected-inundation seed (D-0011)
        out[f"sites/{d.name}/hstar.json"] = json.dumps(hs).encode()
        out[f"sites/{d.name}/meta.json"] = json.dumps(keep).encode()
        fh = ROOT / "results" / "kill_test_v2" / f"{d.name}_floodheight.png"
        if fh.exists():
            out[f"sites/{d.name}/floodheight.png"] = fh.read_bytes()
        ts = ROOT / "results" / "kill_test_v2" / f"{d.name}_ts.png"
        if ts.exists():
            out[f"sites/{d.name}/frozen_test_ts.png"] = ts.read_bytes()
    out["data/sites.json"] = json.dumps(sites).encode()
    return out


def upload_site(sess, bucket: str, dist_id: str):
    s3 = sess.client("s3")
    files: dict[str, bytes] = {}
    for p in (ROOT / "web").rglob("*"):
        if p.is_file():
            files[str(p.relative_to(ROOT / "web")).replace("\\", "/")] = p.read_bytes()
    files.update(site_data())
    for key, body in files.items():
        ct = mimetypes.guess_type(key)[0] or "application/octet-stream"
        if key.endswith(".js"):
            ct = "text/javascript"
        cache = "no-cache" if key.endswith((".html", ".json")) else "max-age=300"
        s3.put_object(Bucket=bucket, Key=f"site/{key}", Body=body, ContentType=ct, CacheControl=cache)
    print(f"uploaded {len(files)} site files", flush=True)
    sess.client("cloudfront").create_invalidation(
        DistributionId=dist_id, InvalidationBatch={"Paths": {"Quantity": 1, "Items": ["/*"]},
                                                   "CallerReference": str(time.time())})


def update_worker(sess, instance_id: str):
    ssm = sess.client("ssm")
    for _ in range(30):
        info = ssm.describe_instance_information(Filters=[{"Key": "InstanceIds", "Values": [instance_id]}])
        if info["InstanceInformationList"]:
            break
        print("waiting for the worker to register with SSM ...", flush=True)
        time.sleep(20)
    else:
        print("worker not in SSM yet; its bootstrap pulls the tarball by itself", flush=True)
        return
    ssm.send_command(InstanceIds=[instance_id], DocumentName="AWS-RunShellScript",
                     Parameters={"commands": ["test -x /opt/riversight/update.sh && /opt/riversight/update.sh && "
                                              "systemctl start --no-block riversight-cycle.service || true"]},
                     Comment="riversight deploy: pull tarball + run a cycle")


def smoke(url: str, since: float, timeout_s: int = 1500) -> dict | None:
    t_end = time.time() + timeout_s
    while time.time() < t_end:
        try:
            with urllib.request.urlopen(f"{url}/live/index.json?t={int(time.time())}", timeout=15) as r:
                idx = json.loads(r.read())
            import pandas as pd
            if pd.Timestamp(idx["cycle_started"]).timestamp() >= since - 120:
                return idx
            print(f"index from {idx['cycle_started']} (waiting for a fresh cycle)", flush=True)
        except Exception as e:
            print(f"smoke: {e!r}", flush=True)
        time.sleep(30)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=os.environ.get("AWS_PROFILE", "riversight"))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--guard-only", action="store_true")
    g.add_argument("--site-only", action="store_true")
    g.add_argument("--code-only", action="store_true")
    ap.add_argument("--worker-ami", choices=["ubuntu", "cool"])
    ap.add_argument("--cool-ami-id")
    ap.add_argument("--instance-type")
    ap.add_argument("--no-smoke", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    sess = session(a.profile)
    if a.guard_only:
        cdk(["deploy", "RiverSightGuard", "--outputs-file", str(OUTPUTS)], a.profile, {"deploy_live": "0"})
        verify_guard(sess)
        return
    if a.site_only or a.code_only:
        o = outputs()
        if a.site_only:
            upload_site(sess, o["BucketName"], o["DistributionId"])
        else:
            upload_code(sess, o["BucketName"])
            update_worker(sess, o["WorkerInstanceId"])
        print(f"done in {time.time() - t0:.0f} s  {o['SiteUrl']}")
        return
    verify_guard(sess)                       # D-0004: refuse to launch EC2 without the guard
    tok, new = approval_token()
    ctx = {"approval_token_sha256": hashlib.sha256(tok.encode()).hexdigest(),
           "origin_secret": env_secret("ORIGIN_SECRET")[0]}       # CloudFront -> approvals Lambda only
    if a.worker_ami:
        ctx["worker_ami"] = a.worker_ami
    if a.cool_ami_id:
        ctx["cool_ami_id"] = a.cool_ami_id
    if a.instance_type:
        ctx["worker_instance_type"] = a.instance_type
    cdk(["deploy", "--all", "--outputs-file", str(OUTPUTS)], a.profile, ctx)
    o = outputs()
    upload_code(sess, o["BucketName"])
    upload_site(sess, o["BucketName"], o["DistributionId"])
    if new:
        sess.client("sns").publish(TopicArn=o["AlertTopicArn"], Subject="RiverSight approval token",
                                   Message=f"Approval token for {o['SiteUrl']}/approvals.html :\n\n{tok}\n\n"
                                           "Keep it private. It is not stored anywhere in the repo.")
    update_worker(sess, o["WorkerInstanceId"])
    print(f"deployed in {time.time() - t0:.0f} s; smoke-testing {o['SiteUrl']}", flush=True)
    if not a.no_smoke:
        idx = smoke(o["SiteUrl"], t0)
        print("SMOKE", "OK" if idx else "TIMEOUT", json.dumps({k: v for k, v in (idx or {}).items() if k != "sites"},
                                                               default=str)[:400])
    print(f"total {time.time() - t0:.0f} s\nURL: {o['SiteUrl']}")


if __name__ == "__main__":
    sys.exit(main())
