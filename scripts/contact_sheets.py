"""SLICE_01 step 3b: contact sheets (daytime frames at the 30-day min / median / max stage) per candidate.

Uses the screening stage (data/raw/iv_screen) and a 30-day NIMS listing (cached as
data/derived/<camId>/list_30d.txt, reused by fetch_sites.py). Writes
results/kill_test/contacts/contact_<camId>.jpg plus 4-up review mosaics in the scratch dir given.

  python scripts/contact_sheets.py CAM1 CAM2 ... [--mosaic-dir DIR]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from riversight.data.join import frames_table, join_frames_to_stage
from riversight.data.nims import NimsClient

DATA = Path("data")
OUT = Path("results/kill_test/contacts")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cams", nargs="+")
    ap.add_argument("--end", default="2026-10-14T00:00:00Z")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--mosaic-dir", type=Path, default=None)
    a = ap.parse_args()
    end = datetime.fromisoformat(a.end.replace("Z", "+00:00"))
    start = end - timedelta(days=a.days)
    cand = pd.read_csv(DATA / "derived" / "candidates.csv", dtype={"nwis_id": str}).set_index("cam_id")
    nims = NimsClient()
    OUT.mkdir(parents=True, exist_ok=True)
    sheets = []
    for cam in a.cams:
        lp = DATA / "derived" / cam / f"list_{a.days}d.txt"
        if lp.exists():
            files = [x for x in lp.read_text().splitlines() if x]
        else:
            files = nims.list_files_range(cam, start, end)
            lp.parent.mkdir(parents=True, exist_ok=True)
            lp.write_text("\n".join(files))
        st = pd.read_parquet(DATA / "raw" / "iv_screen" / f"{cand.loc[cam, 'nwis_id']}.parquet")
        fr = join_frames_to_stage(frames_table(files), st).dropna(subset=["stage_ft"])
        fr = fr[fr["time"].dt.hour.between(16, 22)]  # roughly local midday across CONUS
        if len(fr) < 3:
            print(f"{cam}: too few midday frames ({len(fr)})")
            continue
        picks = [fr["stage_ft"].idxmin(), (fr["stage_ft"] - fr["stage_ft"].median()).abs().idxmin(),
                 fr["stage_ft"].idxmax()]
        tiles = []
        for i in picks:
            p = nims.download(cam, fr.loc[i, "filename"], DATA / "raw", prefix="720")
            img = cv2.imread(str(p))
            img = cv2.resize(img, (480, int(480 * img.shape[0] / img.shape[1])), interpolation=cv2.INTER_AREA)
            cv2.rectangle(img, (0, img.shape[0] - 22), (img.shape[1], img.shape[0]), (0, 0, 0), -1)
            cv2.putText(img, f"{fr.loc[i, 'time']:%m-%d %H:%M}Z  {fr.loc[i, 'stage_ft']:.2f} ft", (6, img.shape[0] - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            tiles.append(img)
        h = min(t.shape[0] for t in tiles)
        sheet = np.hstack([t[:h] for t in tiles])
        bar = np.zeros((24, sheet.shape[1], 3), np.uint8)
        cv2.putText(bar, f"{cam}  swing p95-p05 {cand.loc[cam, 'p95_p05_ft']:.2f} ft", (6, 17),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)
        sheet = np.vstack([bar, sheet])
        cv2.imwrite(str(OUT / f"contact_{cam}.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 80])
        sheets.append(sheet)
        print(f"{cam}: ok", flush=True)
    if a.mosaic_dir:
        a.mosaic_dir.mkdir(parents=True, exist_ok=True)
        for k in range(0, len(sheets), 4):
            grp = sheets[k:k + 4]
            w = max(s.shape[1] for s in grp)
            grp = [cv2.copyMakeBorder(s, 0, 4, 0, w - s.shape[1], cv2.BORDER_CONSTANT) for s in grp]
            cv2.imwrite(str(a.mosaic_dir / f"mosaic_{k // 4:02d}.jpg"), np.vstack(grp), [cv2.IMWRITE_JPEG_QUALITY, 75])


if __name__ == "__main__":
    main()
