"""Render each site's registration reference frame (plus the highest/lowest-stage *fit-window* frames) with a labelled pixel grid, for placing hand transects
(SLICE_01 fallback). Light: one image per site.

  python scripts/render_ref_grid.py --out <dir> [--only CAM ...]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from riversight.killtest import Cfg, choose_reference, thin_frames  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--step", type=int, default=40)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    doc = yaml.safe_load((ROOT / "data/sites/kill_test.yaml").read_text(encoding="utf-8"))
    t1 = pd.Timestamp(doc["window"]["end"]); t0 = t1 - pd.Timedelta(days=30); ts = t0 + pd.Timedelta(days=20)
    for s in doc["sites"]:
        cam = s["cam_id"]
        if a.only and cam not in a.only:
            continue
        d = ROOT / "data/derived" / cam
        cache = d / "registration_cascade.parquet"
        if cache.exists():
            ref_name = pd.read_parquet(cache, columns=["ref"])["ref"].iloc[0]
            img = cv2.imread(str(ROOT / "data/raw/720" / cam / ref_name))
        else:
            f = pd.read_parquet(d / "frames.parquet")
            f = f[(f["time"] >= t0) & (f["time"] < t1)].sort_values("time").reset_index(drop=True)
            f = thin_frames(f, 30).reset_index(drop=True)
            f["window"] = ["fit" if t < ts else "test" for t in f["time"]]
            f["path"] = [str(ROOT / p) for p in f["path"]]
            _, img = choose_reference(f, Cfg())
        panels = [img]
        if cache.exists():  # add the highest- and lowest-stage registered daytime frames, warped to the reference
            reg = pd.read_parquet(cache)
            fr = pd.read_parquet(d / "frames.parquet")[["filename", "time", "stage_ft"]]
            fr = fr[(fr["time"] >= t0) & (fr["time"] < ts)]  # fit window only: never look at test days
            from riversight.killtest import sun_elevation_deg
            r = reg[reg["ok"] == True].merge(fr, on="filename").dropna(subset=["stage_ft"])  # noqa: E712
            r = r[sun_elevation_deg(s["lat"], s["lng"], r["time"]) > 5].reset_index(drop=True)  # real daylight only
            for i in (r["stage_ft"].idxmax(), r["stage_ft"].idxmin()):
                im = cv2.imread(str(ROOT / "data/raw/720" / cam / r.loc[i, "filename"]))
                H = np.array(r.loc[i, "H"]).reshape(3, 3)
                wp = cv2.warpPerspective(im, H, (img.shape[1], img.shape[0]))
                cv2.putText(wp, f"{r.loc[i, 'stage_ft']:.2f} ft", (10, img.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX,
                            0.8, (0, 0, 255), 2, cv2.LINE_AA)
                panels.append(wp)
        out = []
        for img in panels:
            out.append(grid(img, a.step))
        big = np.hstack(out) if len(out) == 1 else np.vstack([np.hstack(out[:2]), np.hstack([out[2], np.zeros_like(out[2])])])
        cv2.imwrite(str(a.out / f"{cam}.jpg"), big, [cv2.IMWRITE_JPEG_QUALITY, 85])
        print(cam, img.shape)


def grid(img, step):
    img = img.copy()
    h, w = img.shape[:2]
    if True:
        for x in range(0, w, step):
            cv2.line(img, (x, 0), (x, h), (0, 255, 255) if x % 200 == 0 else (0, 160, 160), 1)
            cv2.putText(img, str(x), (x + 2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1, cv2.LINE_AA)
        for y in range(0, h, step):
            cv2.line(img, (0, y), (w, y), (255, 0, 255) if y % 200 == 0 else (160, 0, 160), 1)
            cv2.putText(img, str(y), (2, y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 0, 255), 1, cv2.LINE_AA)
    return img


if __name__ == "__main__":
    main()
