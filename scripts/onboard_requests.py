"""W5 "Add a camera" poller (D-0013 W5-2). Runs on the compute box (where worker-q is); light itself.

  python scripts/onboard_requests.py --catalogue      publish live/onboard/catalogue.json (every gauged HIVIS camera,
                                                      eligibility + onboarding status + measured cost per camera)
  python scripts/onboard_requests.py --poll           act on requests (live/approvals/onb-*.json, made by the
                                                      /api/onboard_requests route) and mirror their status to
                                                      live/onboard_requests/<cam>.json + index.json

Only **approved** requests run (the operator approves on /approvals with the operator token). An approved request
for a camera that is not eligible (no gauge stage, inactive, too new, not a river) is closed with the reason and
runs nothing. Eligible ones are submitted once to worker-q (high priority, declared from the measured per-site
peak) as scripts/onboard_site.py <cam>; the result (tier, CV) is written back when the job ends. A tier-B result is
picked up by W1's next deploy (models/onboard/), like every other onboarded site.

AWS: profile `riversight` (aws login), bucket from infra/cdk-outputs.json.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from riversight.onboard import W_END  # noqa: E402
from riversight.onboard.types import camera_type  # noqa: E402

RES = Path(os.environ.get("RIVERSIGHT_RESULTS", ROOT / "results")) / "onboarding"
DATA = Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))
PY = sys.executable
APPROVALS = "live/approvals/"
OUT = "live/onboard_requests/"


def why_not(r) -> str:
    """Eligibility reason, same rules as scripts/onboard_pool.eligible (empty string = eligible)."""
    slots = 365 * 96
    if bool(r.hidden):
        return "camera hidden in NIMS"
    if r.camera_type == "not_a_river":
        return "not a river camera"
    if not bool(r.active_48h):
        return "no image in the last 48 h"
    if r.age_days < 120:
        return "camera younger than 120 days"
    if not (r.iv_n >= 0.6 * slots):
        return "gauge stage (00065) missing for > 40 % of the last 12 months"
    return ""


def catalogue() -> dict:
    pool = pd.read_csv(RES / "pool.csv", dtype={"nwis_id": str}).drop_duplicates("cam_id")
    pool = pool[~pool["hidden"].astype(bool)]                       # cameras hidden in NIMS are not listed publicly
    summ = pd.read_csv(RES / "summary.csv").set_index("cam_id") if (RES / "summary.csv").exists() else pd.DataFrame()
    pool["camera_type"] = [camera_type(c, s, la) for c, s, la in zip(pool["cam_id"], pool["state"], pool["lat"])]
    rows = []
    for r in pool.itertuples():
        st = "not onboarded"
        if r.cam_id in summ.index:
            s = summ.loc[r.cam_id]
            st = (f"onboarded, tier {s['tier']}" + (" (served)" if bool(s["live_eligible"]) else " (not served)")) \
                if s["status"] == "done" else f"onboarding {s['status']}"
        if r.in_kill_test:
            st = "original 20 (frozen test)"
        rows.append({"cam_id": r.cam_id, "name": r.name, "state": r.state, "nwis_id": r.nwis_id, "type": r.camera_type,
                     "swing_ft": None if pd.isna(r.iv_swing_ft) else round(float(r.iv_swing_ft), 2),
                     "eligible": why_not(r) == "", "why_not": why_not(r), "status": st})
    cost = json.loads((RES / "cost.json").read_text(encoding="utf-8"))["per_camera"] if (RES / "cost.json").exists() else {}
    return {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "window_end": W_END.isoformat(),
            "activity_as_of": "camera activity and gauge coverage from the W5 scan (results/onboarding/pool.csv)",
            "cost_per_camera": {k: cost.get(k) for k in ("cpu_s_median", "usd_per_site_median", "mb_downloaded_median",
                                                          "nims_listing_calls_median", "sites_measured")},
            "cameras": rows}


def s3_client():
    import boto3
    return boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "riversight")).client("s3", region_name="us-east-2")


def bucket() -> str:
    return json.loads((ROOT / "infra" / "cdk-outputs.json").read_text(encoding="utf-8"))["RiverSightLive"]["BucketName"]


def put(s3, key: str, obj):
    s3.put_object(Bucket=bucket(), Key=key, Body=json.dumps(obj, default=str).encode(), ContentType="application/json",
                  CacheControl="no-cache")


def get(s3, key: str):
    try:
        return json.loads(s3.get_object(Bucket=bucket(), Key=key)["Body"].read())
    except s3.exceptions.NoSuchKey:
        return None


def submit(cam: str) -> str:
    """worker-q submit of one onboarding; returns the job id. Declared from the measured peak (~5 GB, one site)."""
    R = str(ROOT).replace("\\", "/")
    cmd = ["workerq", "submit", "--project", "riversight", "--priority", "high", "--gpus", "0", "--ram", "7",
           "--cpus", "2", "--node", "local", "--env", f"RIVERSIGHT_RESULTS={R}/results", "--env", f"RIVERSIGHT_DATA={R}/data",
           "--describe", f"W5 Add-a-camera request (approved): {cam}"[:120], "--eta", "90m", "--",
           PY, "scripts/onboard_site.py", cam, "--jobs", "1", "--out", f"{R}/models/onboard"]
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT).stdout + ""
    m = re.search(r"workerq logs (\d+)", out)
    if not m:
        raise RuntimeError(f"worker-q submit failed: {out[-300:]}")
    return m.group(1)


def job_state(job: str) -> str:
    out = subprocess.run(["workerq", "show", job], capture_output=True, text=True).stdout
    m = re.search(r"Backend state\s+(\w+)|State\s+(\w+)", out)
    return (m.group(1) or m.group(2)) if m else "UNKNOWN"


def poll(s3, cat: dict):
    by = {c["cam_id"]: c for c in cat["cameras"]}
    keys, tok = [], None
    while True:
        r = s3.list_objects_v2(Bucket=bucket(), Prefix=APPROVALS + "onb-", **({"ContinuationToken": tok} if tok else {}))
        keys += [o["Key"] for o in r.get("Contents", [])]
        if not r.get("IsTruncated"):
            break
        tok = r["NextContinuationToken"]
    index = []
    for k in keys:
        a = get(s3, k)
        if not a or a.get("kind") != "onboard_request":
            continue
        cam = a["cam_id"]
        st = get(s3, f"{OUT}{cam}.json") or {"cam_id": cam, "approval_id": a["approval_id"], "requested": a["created"]}
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        c = by.get(cam)
        if a["status"] == "pending":
            st["status"] = "awaiting operator approval"
        elif a["status"] == "rejected":
            st["status"] = "rejected by the operator"
        elif "job" not in st and "closed" not in st:            # approved, not acted on yet
            if c is None:
                st.update(status="approved, but not a gauged HIVIS camera", closed=True)
            elif c["status"].startswith(("onboarded", "original")):
                st.update(status=f"already {c['status']}", closed=True)
            elif not c["eligible"]:
                st.update(status=f"approved, but not eligible: {c['why_not']}", closed=True)
            else:                                                    # onboard_site.py adds it to fleet_v2.yaml from pool.csv
                st.update(job=submit(cam), status="queued on worker-q", queued=now_iso)
        elif "job" in st and "closed" not in st:
            js = job_state(st["job"])
            rec_p = RES / f"{cam}.json"
            if js in ("SUCCEEDED", "FAILED", "CANCELLED", "LOST"):
                rec = json.loads(rec_p.read_text(encoding="utf-8")) if rec_p.exists() else {}
                cv = rec.get("cv", {})
                if rec.get("status") == "done":
                    st.update(status=f"onboarded: tier {rec.get('tier')}"
                                     + (" — will be served after the next deploy" if rec.get("live_eligible") else " — not served"),
                              tier=rec.get("tier"), cv_mae_ft=cv.get("mae"), cv_nmae=cv.get("nmae"),
                              tier_reason=cv.get("tier_reason"), closed=True)
                else:
                    st.update(status=f"onboarding failed ({js}): {str(rec.get('error', ''))[:160]}", closed=True)
            else:
                st["status"] = f"running on worker-q (job {st['job']}, {js.lower()})"
        st["updated"] = now_iso
        put(s3, f"{OUT}{cam}.json", st)
        index.append(st)
        print(f"{cam}: {st['status']}", flush=True)
    put(s3, f"{OUT}index.json", {"updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                  "requests": sorted(index, key=lambda x: str(x.get("requested", "")), reverse=True)})
    return index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", action="store_true")
    ap.add_argument("--poll", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="build the catalogue locally, touch no AWS")
    a = ap.parse_args()
    cat = catalogue()
    if a.dry_run:
        prev = ROOT / "runs" / "w5" / "catalogue_preview.json"
        prev.parent.mkdir(parents=True, exist_ok=True)
        prev.write_text(json.dumps(cat, indent=1), encoding="utf-8")
        n = sum(c["eligible"] for c in cat["cameras"])
        print(f"{len(cat['cameras'])} gauged cameras listed, {n} eligible; preview in {prev}")
        return
    s3 = s3_client()
    if a.catalogue:
        put(s3, "live/onboard/catalogue.json", cat)
        print(f"published live/onboard/catalogue.json ({len(cat['cameras'])} cameras)")
    if a.poll:
        poll(s3, cat)


if __name__ == "__main__":
    main()
