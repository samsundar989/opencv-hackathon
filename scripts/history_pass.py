"""SLICE_01B step 2 image pass: register each site's history (piecewise references, riversight.history)
and extract scene features (scripts/scene_features.py, source=history). Cached per site; resumable.

  workerq submit --project riversight --priority low --gpus 0 --ram 10 --cpus 6 --node local --preemptible -- \
    C:/Users/samsu/AppData/Local/Python/pythoncore-3.14-64/python.exe scripts/history_pass.py --jobs 6
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
DATA = Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))


def one(cam: str) -> str:
    import cv2
    cv2.setNumThreads(1)
    os.environ.pop("WORKERQ_PROGRESS", None)   # workers must not overwrite the parent's per-site progress
    from riversight.history import register_history
    import scene_features
    t0 = time.time()
    if not (DATA / "derived" / cam / "history" / "frames.parquet").exists():
        return f"{cam}: no history frames (fetch first)"
    reg = register_history(DATA, cam)
    day = reg[~reg["night"].astype(bool)]
    msg = scene_features.run(cam, "history", "all")
    seg = pd.read_csv(DATA / "derived" / cam / "history" / "segments.csv")
    return (f"{cam}: {len(reg)} frames, {len(day)} daylight, reg ok {day['ok'].mean():.3f}, "
            f"{len(seg)} failure runs ({int(seg['linked'].sum()) if len(seg) else 0} linked); {msg} ({time.time()-t0:.0f}s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", type=Path, default=DATA / "sites" / "kill_test.yaml")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    cams = [s["cam_id"] for s in yaml.safe_load(a.sites.read_text(encoding="utf-8"))["sites"]
            if not a.only or s["cam_id"] in a.only]
    n = 0
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(one, c): c for c in cams}
        for fu in as_completed(futs):
            n += 1
            p = os.environ.get("WORKERQ_PROGRESS")
            if p:
                Path(p).write_text(f"{n / len(cams):.4f}")
            try:
                print(fu.result(), flush=True)
            except Exception:
                print(f"{futs[fu]}: ERROR\n{traceback.format_exc()}", flush=True)


if __name__ == "__main__":
    main()
