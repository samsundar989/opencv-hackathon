"""SPRINT W5 A.1 + B.1: scan every gauged HIVIS camera.

1. NIMS camera catalogue (cached per day: data/raw/onboard/cameras_<date>.json).
2. 12 months of USGS IV 00065 with qualifiers for every gauged camera, from legacy NWIS IV in small
   multi-site batches (≤ 2 requests in flight, exponential backoff on 429/5xx, cached per site under
   data/raw/iv_12m/; never re-fetched).
3. results/onboarding/pool.csv — one row per camera: activity, age, stage stats, outage counts, flags.
4. results/real_outages/catalog_gauges.csv — every gap ≥ 6 h / estimated / equipment-qualified run at every
   gauged camera site (before intersecting with camera frames; scripts/onboard_outages.py does that).

  python scripts/onboard_scan.py            (network-bound, light CPU; ~100 IV requests)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd
import yaml
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from riversight.data.nims import NimsClient, camera_from_record  # noqa: E402
from riversight.data.nwis import RateLimited, _Transient  # noqa: E402
from riversight.onboard import W_END, W_START  # noqa: E402
from riversight.onboard.gauges import cache_path, fetch_iv_qualified, scan_outages, stage_stats  # noqa: E402

DATA = Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))
IV = DATA / "raw" / "iv_12m"


def cameras(nims: NimsClient) -> list[dict]:
    p = DATA / "raw" / "onboard" / f"cameras_{datetime.now(timezone.utc).date().isoformat()}.json"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(nims._get("https://api.waterdata.usgs.gov/nims/v0/cameras").json()), encoding="utf-8")
    return json.loads(p.read_text(encoding="utf-8"))


@retry(retry=retry_if_exception_type((_Transient, httpx.TransportError)), stop=stop_after_attempt(6),
       wait=wait_exponential(multiplier=2, min=4, max=120), reraise=True)
def fetch_batch(http: httpx.Client, sites: list[str]) -> int:
    got = fetch_iv_qualified(http, sites, W_START, W_END)
    for s in sites:
        if s in got:
            got[s].to_parquet(cache_path(IV, s), index=False)
        else:
            (IV / f"{s}.none").touch()
    return len(got)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--inflight", type=int, default=2, help="concurrent IV requests (≤ 4, CLAUDE.md rule 6)")
    ap.add_argument("--min-gap-h", type=float, default=6.0)
    a = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    nims = NimsClient(api_key=os.getenv("USGS_API_KEY"))
    recs = cameras(nims)
    cams = [camera_from_record(r) for r in recs]
    gauged = [c for c in cams if c.gauged]
    sites = sorted({c.nwis_id for c in gauged})
    print(f"{len(cams)} cameras, {len(gauged)} gauged, {len(sites)} distinct gauges", flush=True)

    IV.mkdir(parents=True, exist_ok=True)
    todo = [s for s in sites if not cache_path(IV, s).exists() and not (IV / f"{s}.none").exists()]
    batches = [todo[i:i + a.batch] for i in range(0, len(todo), a.batch)]
    print(f"{len(todo)} gauges to fetch in {len(batches)} requests", flush=True)
    http = httpx.Client(timeout=600, headers={"User-Agent": "RiverSight/0.1 (OpenCV AI Competition 2026)"},
                        follow_redirects=True)
    t0, done = time.time(), 0
    with ThreadPoolExecutor(min(a.inflight, 4)) as ex:
        for k, n in enumerate(ex.map(lambda b: fetch_batch(http, b), batches), 1):
            done += n
            p = os.environ.get("WORKERQ_PROGRESS")
            if p:
                Path(p).write_text(f"{k / len(batches):.4f}")
            if k % 5 == 0 or k == len(batches):
                print(f"  {k}/{len(batches)} requests, {done} series, {time.time() - t0:.0f}s", flush=True)

    kill = {s["cam_id"] for s in yaml.safe_load((DATA / "sites" / "kill_test.yaml").read_text(encoding="utf-8"))["sites"]}
    rejected = set((yaml.safe_load((DATA / "sites" / "kill_test.yaml").read_text(encoding="utf-8")).get("rejected") or {}))
    now = W_END
    rows, events = [], []
    stats_cache: dict[str, tuple[dict, list]] = {}
    for c in gauged:
        if c.nwis_id not in stats_cache:
            p = cache_path(IV, c.nwis_id)
            df = pd.read_parquet(p) if p.exists() else None
            stats_cache[c.nwis_id] = (stage_stats(df), scan_outages(df, a.min_gap_h) if df is not None else [])
        st, ev = stats_cache[c.nwis_id]
        for e in ev:
            events.append({"cam_id": c.cam_id, "nwis_id": c.nwis_id, "state": c.state, **e})
        rows.append({"cam_id": c.cam_id, "nwis_id": c.nwis_id, "state": c.state, "name": c.name, "lat": c.lat, "lng": c.lng,
                     "hidden": c.hidden, "created": str(c.created), "newest_image": str(c.newest_image),
                     "age_days": round(c.age_days(now) or -1, 1), "active_48h": c.active(48, datetime.now(timezone.utc)),
                     "in_kill_test": c.cam_id in kill, "rejected_slice01": c.cam_id.split("___")[0] in rejected,
                     **st, "n_gaps_6h": sum(e["kind"] == "gap" for e in ev),
                     "n_estimated_6h": sum(e["kind"] == "estimated" for e in ev),
                     "n_qualified_6h": sum(e["kind"] == "qualified" for e in ev),
                     "outage_hours": round(sum(e["hours"] for e in ev if e["kind"] == "gap"), 1)})
    out = ROOT / "results" / "onboarding"
    out.mkdir(parents=True, exist_ok=True)
    pool = pd.DataFrame(rows)
    pool.round(4).to_csv(out / "pool.csv", index=False)
    ro = ROOT / "results" / "real_outages"
    ro.mkdir(parents=True, exist_ok=True)
    cat = pd.DataFrame(events, columns=["cam_id", "nwis_id", "state", "kind", "start", "end", "hours", "v_before", "v_after", "codes"])
    cat.round(3).to_csv(ro / "catalog_gauges.csv", index=False)
    print(f"pool: {len(pool)} gauged cameras, {int(pool['active_48h'].sum())} active, {int((pool['iv_n'] > 0).sum())} with 00065 "
          f"in the window; catalogue: {len(cat)} events ({cat['kind'].value_counts().to_dict()})")


if __name__ == "__main__":
    main()
