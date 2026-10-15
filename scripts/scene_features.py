"""SLICE_01B: registered daylight frames → per-block scene features (cached per site).

  --source kill30 --window fit    the SLICE_01 30-day cache, first 20 days (reproduction gate, step 1)
  --source kill30 --window test   the 10 frozen test days (step 4 only — scored once)
  --source history                the long history fetched by scripts/fetch_history.py (step 2)

Output: data/derived/<cam>/scene_<source>_<window>.npz with
  t (int64 ns UTC), filename, h (gauge stage ft, NaN if none), F (n, 3600, 5) float16 block features,
  ref_small (180×320×3 reference frame at feature resolution), ref (reference filename).

Image pass over thousands of frames → run through worker-q (D-0005):
  workerq submit --project riversight --priority low --gpus 0 --ram 4 --cpus 4 --node local -- \
    C:/Users/samsu/AppData/Local/Python/pythoncore-3.14-64/python.exe scripts/scene_features.py --source kill30 --window fit --jobs 4
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DATA = Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))


def _progress(frac: float):
    p = os.environ.get("WORKERQ_PROGRESS")
    if p:
        try:
            Path(p).write_text(f"{frac:.4f}")
        except OSError:
            pass


def kill30_frames(cam: str, window: str):
    """(frames with H for registered daylight frames in the window, reference image, ref filename)."""
    from riversight.killtest import Cfg, register_site
    doc = yaml.safe_load((DATA / "sites" / "kill_test.yaml").read_text(encoding="utf-8"))
    t1 = pd.Timestamp(doc["window"]["end"])
    t0 = t1 - pd.Timedelta(days=doc["window"]["days"])
    ts = t0 + pd.Timedelta(days=doc["window"]["fit_days"])
    frames, _, ref_i, ref, reg = register_site(cam, DATA, t0, ts, t1, Cfg())
    f = frames.join(reg[["ok", "H", "night"]], how="inner")
    f = f[f["ok"] & (f["window"] == window)]
    return f, ref, frames.loc[ref_i, "filename"]


def history_frames(cam: str, window: str):
    from riversight.history import load_registered_history
    return load_registered_history(DATA, cam)


def run(cam: str, source: str, window: str) -> str:
    import cv2
    cv2.setNumThreads(1)
    from riversight.vision.scene_features import block_features, warp_small
    out = DATA / "derived" / cam / f"scene_{source}_{window}.npz"
    if out.exists():
        return f"{cam}: cached"
    f, ref, ref_name = (kill30_frames if source == "kill30" else history_frames)(cam, window)
    shape = ref.shape[:2]
    F, t, names, h = [], [], [], []
    for _, r in f.iterrows():
        img = cv2.imread(str(ROOT / r["path"]) if not Path(r["path"]).is_absolute() else r["path"])
        if img is None:
            continue
        H = np.array(r["H"], float).reshape(3, 3)
        F.append(block_features(warp_small(img, H, shape)).astype(np.float16))
        t.append(pd.Timestamp(r["time"]).value)
        names.append(r["filename"])
        h.append(r["stage_ft"])
    tmp = out.with_suffix(".part.npz")
    np.savez_compressed(tmp, t=np.array(t, np.int64), filename=np.array(names), h=np.array(h, float),
                        F=np.array(F), ref_small=warp_small(ref, None, shape), ref=np.array(ref_name))
    tmp.replace(out)
    return f"{cam}: {len(t)} frames"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["kill30", "history"], required=True)
    ap.add_argument("--window", default="fit", help="kill30: fit|test; history: all")
    ap.add_argument("--sites", type=Path, default=DATA / "sites" / "kill_test.yaml")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    cams = [s["cam_id"] for s in yaml.safe_load(a.sites.read_text(encoding="utf-8"))["sites"]
            if not a.only or s["cam_id"] in a.only]
    done = 0
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(run, c, a.source, a.window): c for c in cams}
        for fu in as_completed(futs):
            done += 1
            _progress(done / len(cams))
            try:
                print(fu.result(), flush=True)
            except Exception:
                print(f"{futs[fu]}: ERROR\n{traceback.format_exc()}", flush=True)


if __name__ == "__main__":
    main()
