"""W4: DINOv2 patch tokens (cv2.dnn) for every calibration frame the v1 scene model trains on.

  --fit-basis   fixed global PCA basis (384 → K dims) from daylight frames of sites that are NOT in the
                kill test (no labels, no kill-test pixels) → results/v2/dino_pca_basis.npz
  (default)     per kill-test site: the exact frames of scene_history_all.npz ∪ scene_kill30_fit.npz with
                t < 2026-10-03 00Z (the D-0007 calibration set; the frozen test days are never opened),
                warped with the same homography and `warp_small` as v1, → data/derived/<cam>/dino_calib.npz:
                  filename, t, P (n, 448, K) float16 projected patch tokens, cls (n, 384) float16,
                  gmean (n, 384) float16 mean patch token.
  --live        the frames of scene_kill30_test.npz (Oct 3–14) → dino_live.npz, used ONLY to refit the live
                shadow bundles on all data, exactly as the v1 live models are (D-0008 ruling 5). Never used by
                v2_cv.py; the frozen kill-test numbers are not recomputed.

Run via worker-q (CPU, ~36k frames):
  workerq submit --project riversight --priority high --ram 8 --cpus 8 -- python scripts/v2_dino_features.py --jobs 4
"""
from __future__ import annotations

import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DATA = Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))
CUT = pd.Timestamp("2026-10-03", tz="UTC")
BASIS = ROOT / "results" / "v2" / "dino_pca_basis.npz"
K = 48


def kill_cams() -> list[str]:
    return [s["cam_id"] for s in yaml.safe_load((DATA / "sites" / "kill_test.yaml").read_text(encoding="utf-8"))["sites"]]


def fit_basis(per_site: int = 60, seed: int = 0):
    import cv2
    from riversight.killtest import Cfg, is_night
    from riversight.vision import dino_features as D
    kill = set(kill_cams())
    rng = np.random.default_rng(seed)
    net = D.load_net()
    toks, used = [], []
    for d in sorted((DATA / "raw" / "720").iterdir()):
        if d.name in kill or not d.is_dir():
            continue
        files = sorted(d.glob("*.jpg"))
        for f in rng.permutation(files)[:per_site] if len(files) > per_site else files:
            img = cv2.imread(str(f))
            if img is None or is_night(img, Cfg()):
                continue
            small = cv2.resize(img, (320, 180), interpolation=cv2.INTER_AREA)
            toks.append(D.tokens(net, small)[1:])
            used.append(f.name)
    T = np.concatenate(toks).astype(np.float64)
    mu = T.mean(0)
    U, S, Vt = np.linalg.svd(T - mu, full_matrices=False)
    ev = S ** 2 / np.sum(S ** 2)
    BASIS.parent.mkdir(parents=True, exist_ok=True)
    np.savez(BASIS, mean=mu.astype(np.float32), components=Vt[:K].astype(np.float32), explained=ev[:K],
             frames=np.array(used), model_sha256=D.MODEL_SHA256)
    print(f"basis from {len(used)} frames of {len(set(u.split('___')[0] for u in used))} non-kill-test sites; "
          f"K={K} explains {ev[:K].sum():.3f} of token variance (K=16: {ev[:16].sum():.3f})")


def calib_frames(cam: str, live: bool = False) -> pd.DataFrame:
    """filename, t, path, H for the v1 calibration frames (t < CUT), H from the registration v1 used.
    live=True: the scene_kill30_test.npz frames instead (live refit only)."""
    d = DATA / "derived" / cam
    names = []
    for n in (("scene_kill30_test.npz",) if live else ("scene_history_all.npz", "scene_kill30_fit.npz")):
        p = d / n
        if p.exists():
            z = np.load(p)
            names.append(pd.DataFrame({"filename": z["filename"], "t": pd.to_datetime(z["t"], utc=True)}))
    df = pd.concat(names).drop_duplicates("filename")
    if not live:
        df = df[df["t"] < CUT]
    hist = pd.read_parquet(d / "history" / "frames.parquet", columns=["filename", "path"]).merge(
        pd.read_parquet(d / "history" / "registration.parquet", columns=["filename", "H"]), on="filename")
    k30 = pd.read_parquet(d / "frames.parquet", columns=["filename", "path"]).merge(
        pd.read_parquet(d / "registration_cascade.parquet", columns=["filename", "H"]), on="filename")
    reg = pd.concat([hist, k30]).drop_duplicates("filename")
    out = df.merge(reg, on="filename", how="left").sort_values("t").reset_index(drop=True)
    miss = out["H"].isna().sum()
    if miss:
        raise RuntimeError(f"{cam}: {miss} calibration frames without a homography")
    return out


def run(cam: str, live: bool = False) -> str:
    import cv2
    cv2.setNumThreads(2)
    from riversight.vision import dino_features as D
    from riversight.vision.scene_features import warp_small
    out = DATA / "derived" / cam / ("dino_live.npz" if live else "dino_calib.npz")
    if out.exists():
        return f"{cam}: cached"
    t0 = time.time()
    basis = dict(np.load(BASIS))
    f = calib_frames(cam, live)
    ref_name = pd.read_parquet(DATA / "derived" / cam / "registration_cascade.parquet", columns=["ref"])["ref"].iloc[0]
    ref = cv2.imread(str(DATA / "raw" / "720" / cam / ref_name))
    net = D.load_net()
    P, C, G, keep = [], [], [], []
    for i, r in f.iterrows():
        path = Path(r["path"]) if Path(r["path"]).is_absolute() else ROOT / r["path"]
        img = cv2.imread(str(path))
        if img is None:
            continue
        small = warp_small(img, np.array(r["H"], float).reshape(3, 3), ref.shape[:2])
        tok = D.tokens(net, small)
        P.append(D.project(tok[1:], basis).astype(np.float16))
        C.append(tok[0].astype(np.float16))
        G.append(tok[1:].mean(0).astype(np.float16))
        keep.append(i)
    f = f.loc[keep]
    tmp = out.with_suffix(".part.npz")
    np.savez_compressed(tmp, filename=f["filename"].to_numpy(str), t=f["t"].astype("int64").to_numpy(),
                        P=np.array(P), cls=np.array(C), gmean=np.array(G), model_sha256=D.MODEL_SHA256)
    tmp.replace(out)
    return f"{cam}: {len(keep)} frames ({time.time() - t0:.0f}s)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit-basis", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    if a.fit_basis:
        return fit_basis()
    cams = [c for c in kill_cams() if not a.only or c in a.only]
    n = 0
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(run, c, a.live): c for c in cams}
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
