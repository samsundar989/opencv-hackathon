"""Prospective live evaluation (D-0010 §1): score the frozen live models' readings against USGS gauges.

  python scripts/score_prospective.py --freeze           write results/live_prospective/frozen_models.json (once)
  python scripts/score_prospective.py --s3 <bucket>      score from the live bucket, write results/live_prospective/
  python scripts/score_prospective.py --local [DIR]      score from live_local/ (development)

The worker runs the same scorer hourly into s3://<bucket>/live/prospective/ (riversight.live.prospective);
this script pulls those numbers into the repo for the daily commit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "results" / "live_prospective"
FROZEN = OUT / "frozen_models.json"


def freeze():
    from riversight.live.prospective import WINDOW_START
    if FROZEN.exists():
        sys.exit(f"refusing: {FROZEN} exists (frozen once)")
    models = {}
    for d in sorted((ROOT / "models" / "sites").iterdir()):
        if not (d / "meta.json").exists() or d.name.startswith("."):
            continue
        m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        sha = hashlib.sha256((d / "scene_model.npz").read_bytes()).hexdigest()
        assert sha == m["model_sha"], d.name
        models[d.name] = {"model_sha": sha, "nwis_id": m["nwis_id"], "trained_at": m["trained_at"],
                          "n_calib_frames": m["n_calib_frames"], "calib_end": m["calib_end"],
                          "frozen_config_sha": m["frozen_config_sha"], "tier": m["tier"]}
    doc = {"decision": "D-0010 §1; window per D-0011 W1-7",
           "window_start_utc": WINDOW_START.isoformat(),
           "first_cool_cycle": {"cycle_started": "2026-10-23T21:28:10Z", "code_sha": "f5927c4",
                                "instance": "i-07bb99b1b2140b900 (m9g.large, COOL G5 ami-0d9a06f3c16d66f9e)"},
           "pre_registration": "D-0010 committed ~16:15 CT Oct 23, before the first COOL cycle (16:28 CT)",
           "served_check": "the model_sha prefix in every reading of the first COOL cycle matches these bundles (18 sites "
                           "served; Pecatonica and E Fork Little Miami had no new frame)",
           "bundles": "scripts/export_site_models.py, worker-q job 3710 (live models, D-0007 setting refit on all data)",
           "frozen_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "models": models}
    OUT.mkdir(parents=True, exist_ok=True)
    FROZEN.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"froze {len(models)} models -> {FROZEN}")


def freeze_onboarded():
    """D-0012: the tier-B onboarded bundles as deployed, scored as their own group from their first live cycle."""
    out = OUT / "frozen_models_onboarded.json"
    if out.exists():
        sys.exit(f"refusing: {out} exists (frozen once)")
    models = {}
    for d in sorted((ROOT / "models" / "onboard").iterdir()):
        if not (d / "meta.json").exists():
            continue
        m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        if m.get("tier") not in ("A", "B"):
            continue
        sha = hashlib.sha256((d / "scene_model.npz").read_bytes()).hexdigest()
        assert sha == m["model_sha"], d.name
        models[d.name] = {"model_sha": sha, "nwis_id": m["nwis_id"], "trained_at": m["trained_at"], "tier": m["tier"],
                          "n_calib_frames": m["n_calib_frames"], "calib_end": m["calib_end"]}
    doc = {"decision": "D-0012 Q-0012 option 1 (onboarded group, never mixed with the frozen 20); rules of D-0010 §1",
           "group": "onboarded", "window_start_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "note": "frozen at deploy time, before the first cycle that serves these bundles",
           "bundles": "W5 onboarding (models/onboard, frozen D-0007 setting, 12 months to 2026-10-23)",
           "frozen_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "models": models}
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"froze {len(models)} onboarded models -> {out}")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--freeze", action="store_true")
    g.add_argument("--freeze-onboarded", action="store_true")
    g.add_argument("--s3", metavar="BUCKET")
    g.add_argument("--local", nargs="?", const=str(ROOT / "live_local"))
    ap.add_argument("--profile", default="riversight")
    a = ap.parse_args()
    if a.freeze:
        return freeze()
    if a.freeze_onboarded:
        return freeze_onboarded()
    from riversight.live import prospective
    from riversight.live.store import LocalStore, S3Store
    if a.s3:
        import boto3
        store = S3Store(a.s3, boto3.Session(profile_name=a.profile, region_name="us-east-2"))
    else:
        store = LocalStore(Path(a.local))
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    summary = prospective.run(store, frozen)
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("readings.csv", "per_site.csv"):
        b = store.get_bytes(f"live/prospective/{name}")
        if b:
            (OUT / name).write_bytes(b.replace(b"\r\n", b"\n"))
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: summary.get(k) for k in ("scored_until_utc", "sites_scored", "median_of_site_mae_ft",
                                                   "sites_camera_beats_lkv24")}, default=str))
    print(json.dumps(summary.get("fleet", {}), default=str)[:600])


if __name__ == "__main__":
    main()
