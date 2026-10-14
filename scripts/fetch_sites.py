"""SLICE_01 step 4: fetch 30 days of 720-px frames + gauge stage for every site in a sites YAML.

One shared pool of <=4 concurrent downloads across all sites (USGS etiquette). Cached under
data/raw/720/<camId>/; never re-downloads. Writes data/derived/<camId>/frames.parquet
(filename, time, stage_ft, stage_dt_min, path).

  python scripts/fetch_sites.py --sites data/sites/kill_test.yaml --end 2026-10-14T00:00:00Z --days 30
"""
from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml
from dotenv import load_dotenv

from riversight.data.join import frames_table, join_frames_to_stage
from riversight.data.nims import NimsClient
from riversight.data.nwis import NwisClient, RateLimited

DATA = Path("data")


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", type=Path, default=DATA / "sites" / "kill_test.yaml")
    ap.add_argument("--end", default="2026-10-14T00:00:00Z")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--prefix", default="720")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    end = datetime.fromisoformat(a.end.replace("Z", "+00:00"))
    start = end - timedelta(days=a.days)
    sites = yaml.safe_load(a.sites.read_text(encoding="utf-8"))["sites"]
    nims, nwis = NimsClient(), NwisClient()
    raw = DATA / "raw"

    listings = {}
    for s in sites:
        cam = s["cam_id"]
        lp = DATA / "derived" / cam / f"list_{a.days}d.txt"
        if lp.exists():
            files = [x for x in lp.read_text().splitlines() if x]
        else:
            files = nims.list_files_range(cam, start, end)
            lp.parent.mkdir(parents=True, exist_ok=True)
            lp.write_text("\n".join(files))
        listings[cam] = files
        print(f"{cam}: {len(files)} frames", flush=True)

    jobs = [(cam, f) for cam, fs in listings.items() for f in fs
            if not (raw / a.prefix / cam / f).exists()]
    print(f"{len(jobs)} images to download ({sum(map(len, listings.values()))} total)", flush=True)
    t0, errs = time.time(), []
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(nims.download, cam, f, raw, a.prefix): (cam, f) for cam, f in jobs}
        for i, fu in enumerate(as_completed(futs), 1):
            try:
                fu.result()
            except Exception as e:
                errs.append((*futs[fu], repr(e)[:120]))
            if i % 500 == 0:
                print(f"  {i}/{len(jobs)} {time.time()-t0:.0f}s, {len(errs)} errors", flush=True)

    for s in sites:
        cam = s["cam_id"]
        d = DATA / "derived" / cam
        sp = d / "stage.parquet"
        if sp.exists():
            stage = pd.read_parquet(sp)
        else:
            for attempt in range(3):
                try:
                    stage = nwis.stage(str(s["nwis_id"]).zfill(8), start - timedelta(hours=1), end + timedelta(hours=1))
                    break
                except RateLimited as e:  # one quiet wait, never a retry storm
                    print(f"rate limited; sleeping {e.retry_after_s:.0f}s", flush=True)
                    time.sleep(e.retry_after_s + 5)
            stage.to_parquet(sp, index=False)
        frames = frames_table(listings[cam])
        j = join_frames_to_stage(frames, stage)
        j["path"] = [str(raw / a.prefix / cam / f) for f in j["filename"]]
        j = j[[Path(p).exists() for p in j["path"]]]
        j.to_parquet(d / "frames.parquet", index=False)
        print(f"{cam}: {len(j)} frames on disk, {j['stage_ft'].notna().sum()} with stage", flush=True)
    print(f"done; {len(errs)} download errors")
    for e in errs[:20]:
        print("ERR", *e)


if __name__ == "__main__":
    main()
