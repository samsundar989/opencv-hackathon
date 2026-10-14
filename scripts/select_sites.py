"""SLICE_01 step 3: screen every catalog camera for the kill test.

Stage variability for all cameras via batched legacy NWIS IV requests (~40 sites/request, so the whole
catalog costs ~20 requests), then a 3-day image listing (frames/day) only for the shortlist.
Writes data/derived/candidates.csv. Ground truth for evaluation is fetched later from the OGC API.

  python scripts/select_sites.py --end 2026-10-14T00:00:00Z --days 30
"""
from __future__ import annotations

import argparse
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from riversight.data.join import stage_variability
from riversight.data.nims import NimsClient
from riversight.data.nwis import legacy_iv_multi

DATA = Path("data")
SMALL_RIVER = re.compile(r"(Creek|_Ck_|_Ck$|Branch|_Br_|Brook|Run_|Bayou|Kill_|_Fk_|Fork)", re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", default="2026-10-14T00:00:00Z")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--min-swing", type=float, default=0.4)
    a = ap.parse_args()
    end = datetime.fromisoformat(a.end.replace("Z", "+00:00"))
    start = end - timedelta(days=a.days)
    cams = pd.read_csv(DATA / "cameras_all.csv", dtype={"nwis_id": str})
    cache = DATA / "raw" / "iv_screen"
    cache.mkdir(parents=True, exist_ok=True)

    sites = sorted(set(cams["nwis_id"]))
    stage: dict[str, pd.DataFrame] = {}
    for b in range(0, len(sites), a.batch):
        chunk = sites[b:b + a.batch]
        missing = [s for s in chunk if not (cache / f"{s}.parquet").exists() and not (cache / f"{s}.none").exists()]
        if missing:
            got = legacy_iv_multi(missing, start, end)
            for s in missing:
                if s in got:
                    got[s].to_parquet(cache / f"{s}.parquet", index=False)
                else:
                    (cache / f"{s}.none").touch()
            print(f"batch {b // a.batch + 1}: {len(got)}/{len(missing)} sites with stage", flush=True)
            time.sleep(1.0)
        for s in chunk:
            if (cache / f"{s}.parquet").exists():
                stage[s] = pd.read_parquet(cache / f"{s}.parquet")

    rows = []
    for r in cams.itertuples():
        st = stage.get(r.nwis_id)
        v = stage_variability(st) if st is not None else stage_variability(pd.DataFrame({"value": []}))
        rows.append({"cam_id": r.cam_id, "nwis_id": r.nwis_id, "state": r.state, "lat": r.lat, "lng": r.lng,
                     "small_river": bool(SMALL_RIVER.search(r.cam_id)), **v})
    df = pd.DataFrame(rows)
    short = df[(df["p95_p05_ft"] >= a.min_swing) | ((df["state"] == "TX") & (df["p95_p05_ft"] >= 0.2))]
    print(f"{df['n'].gt(0).sum()} cameras have stage; shortlist {len(short)} (swing >= {a.min_swing} ft or TX >= 0.2)")

    nims = NimsClient()
    fpd = {}
    for cam in short["cam_id"]:
        lp = DATA / "derived" / cam / "list_3d.txt"
        if lp.exists():
            files = [x for x in lp.read_text().splitlines() if x]
        else:
            files = nims.list_files(cam, after=end - timedelta(days=3), before=end, limit=1000, recent=False)
            lp.parent.mkdir(parents=True, exist_ok=True)
            lp.write_text("\n".join(files))
            time.sleep(0.3)
        fpd[cam] = len(files) / 3.0
    df["frames_per_day"] = df["cam_id"].map(fpd)
    df.sort_values("p95_p05_ft", ascending=False).to_csv(DATA / "derived" / "candidates.csv", index=False)
    print("wrote data/derived/candidates.csv")


if __name__ == "__main__":
    main()
