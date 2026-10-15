"""SLICE_01B step 3: tune the scene model inside the history only (forward-chaining monthly CV, ≥ 7-day gap).

Training data per site = history frames (scene_history_all.npz) ∪ SLICE_01 fit-window frames before
2026-10-03 00Z (scene_kill30_fit.npz), deduplicated by filename. Nothing from the frozen test days.

Folds: for each calendar month M of the site's data, train on frames before (start of M − 7 days), test on
frames in M. A fold needs ≥ 150 training frames spanning ≥ 30 days and ≥ 20 test frames.

Grid (the only knobs, SLICE_01B): reliability threshold {0.80, 0.85, 0.90} × ridge λ {0.3, 1, 3} ×
smoothing {3 h causal median, 1-D Kalman} × block size {4, 8} = 36 settings.
Kalman: q = variance of the training gauge's hourly increments; r = var(LOO residuals of the training
fit) · (1 − ρ₁) (closed-form kernel-ridge leave-one-out; ρ₁ = lag-1 autocorrelation).

Selection rule (fixed before any result was seen): the global setting maximises the number of sites that
meet the P1 criterion on pooled out-of-fold predictions (MAE ≤ 0.25 ft or MAE / (p95 − p5 of the site's
training stage) ≤ 10 %); ties → lower median nMAE across sites → lower median MAE.

Run via worker-q:  scripts/scene_tune.py --jobs 6   (per-site results cached in data/derived/<cam>/tune_cv.npz)
Then:              scripts/scene_tune.py --summarise   → results/scene/tune_*.csv
"""
from __future__ import annotations

import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")   # one BLAS thread per worker process (set before numpy)

import argparse
import itertools
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
CUT = pd.Timestamp("2026-10-03", tz="UTC")       # calibration ends here (D-0006); test days start Oct 4 00Z
GAP = pd.Timedelta("7D")
THRS = (0.80, 0.85, 0.90)
LAMS = (0.3, 1.0, 3.0)
SMOOTH = ("median3h", "kalman")
BSS = (4, 8)
MIN_ROI = 50


def load_train(cam: str):
    """(t, h, F float16 at block size 4) of all calibration frames, time-sorted."""
    parts = []
    for name in ("scene_history_all.npz", "scene_kill30_fit.npz"):
        p = DATA / "derived" / cam / name
        if p.exists():
            z = np.load(p)
            parts.append(pd.DataFrame({"t": z["t"], "h": z["h"], "fn": z["filename"], "src": name, "k": np.arange(len(z["t"]))}))
            parts[-1].attrs["F"] = z["F"]
    if not parts:
        return None
    F_all = {d["src"].iloc[0]: d.attrs["F"] for d in parts if len(d)}
    df = pd.concat(parts, ignore_index=True)
    df["t"] = pd.to_datetime(df["t"], utc=True)
    df = df[(df["t"] < CUT) & np.isfinite(df["h"])].drop_duplicates("fn").sort_values("t").reset_index(drop=True)
    F = np.stack([F_all[s][k] for s, k in zip(df["src"], df["k"])]) if len(df) else np.zeros((0, 3600, 5), np.float16)
    return pd.DatetimeIndex(df["t"]), df["h"].to_numpy(float), F


def gauge_series(cam: str) -> pd.Series:
    parts = []
    for p in (DATA / "derived" / cam / "history" / "stage.parquet", DATA / "derived" / cam / "stage.parquet"):
        if p.exists():
            s = pd.read_parquet(p)
            parts.append(pd.Series(s["value"].to_numpy(float), index=pd.DatetimeIndex(s["time"])))
    g = pd.concat(parts).sort_index()
    g = g[~g.index.duplicated()]
    return g[g.index < CUT]


def month_folds(t: pd.DatetimeIndex):
    out = []
    for m in pd.date_range(t[0].floor("D").replace(day=1), t[-1], freq="MS"):
        m_end = m + pd.offsets.MonthBegin(1)
        tr = t < (m - GAP)
        te = (t >= m) & (t < m_end)
        if tr.sum() >= 150 and (t[tr][-1] - t[tr][0]).days >= 30 and te.sum() >= 20:
            out.append((m.strftime("%Y-%m"), tr, te))
    return out


def _eig_ridge(A_tr, A_te, y):
    """Standardise on train, linear kernel /D, eigendecompose once; returns closure lam → (pred, loo_resid)."""
    mu = A_tr.mean(0)
    sd = A_tr.std(0) + 1e-3
    A = (A_tr - mu) / sd
    B = (A_te - mu) / sd
    D = A.shape[1]
    K = (A @ A.T).astype(np.float64) / D
    Kb = (B @ A.T).astype(np.float64) / D
    e, V = np.linalg.eigh(K)
    ym = y.mean()
    Vy = V.T @ (y - ym)

    def solve(lam):
        c = lam * 0.05
        inv = 1.0 / (e + c)
        alpha = V @ (inv * Vy)
        diag_inv = (V ** 2) @ inv                      # diag((K + cI)^-1)
        loo = alpha / diag_inv                         # y_i − ŷ_(−i) for kernel ridge (centring ignored)
        return Kb @ alpha + ym, loo
    return solve


def tune_site(cam: str) -> str:
    from riversight.calib.flood_height_map import fit_thr
    from riversight.calib.scene_regressor import causal_median, kalman_1d, kalman_params
    from riversight.vision.scene_features import pool_blocks
    out = DATA / "derived" / cam / "tune_cv.npz"
    if out.exists():
        return f"{cam}: cached"
    t0 = time.time()
    L = load_train(cam)
    if L is None or len(L[0]) < 200:
        return f"{cam}: too little calibration data ({0 if L is None else len(L[0])} frames)"
    t, h, F16 = L
    folds = month_folds(t)
    if not folds:
        return f"{cam}: no eligible forward-chaining folds ({len(t)} frames, {(t[-1]-t[0]).days} days)"
    g = gauge_series(cam)
    keys = list(itertools.product(BSS, THRS, LAMS, SMOOTH))
    P = {k: np.full(len(h), np.nan) for k in keys}
    nroi = {k: [] for k in keys}
    fold_id = np.full(len(h), "", dtype=object)
    for bs in BSS:
        X = F16.astype(np.float32) if bs == 4 else pool_blocks(F16.astype(np.float32))
        for name, tr, te in folds:
            fold_id[te] = name
            M = fit_thr(X[tr], h[tr])
            q, _ = kalman_params(g[g.index < t[tr][-1]].index, g[g.index < t[tr][-1]].values, np.zeros(4))
            for thr in THRS:
                roi = M.acc >= thr
                if roi.sum() < MIN_ROI:
                    roi = np.ones_like(roi)
                solve = _eig_ridge(X[tr][:, roi].reshape(tr.sum(), -1), X[te][:, roi].reshape(te.sum(), -1), h[tr])
                for lam in LAMS:
                    p, loo = solve(lam)
                    r = float(np.var(loo)) * (1 - np.clip(np.corrcoef(loo[:-1], loo[1:])[0, 1], 0, 0.95))
                    sm = {"median3h": causal_median(t[te], p, "3h"), "kalman": kalman_1d(t[te], p, q, max(r, 1e-6))[0]}
                    for s in SMOOTH:
                        P[(bs, thr, lam, s)][te] = sm[s]
                        nroi[(bs, thr, lam, s)].append(int(roi.sum()))
    np.savez_compressed(out, t=t.asi8, h=h, fold=fold_id.astype(str), keys=np.array([f"{a}|{b}|{c}|{d}" for a, b, c, d in keys]),
                        P=np.stack([P[k] for k in keys]), nroi=np.array([np.median(nroi[k]) for k in keys]),
                        p5=np.quantile(h, 0.05), p95=np.quantile(h, 0.95), span_days=(t[-1] - t[0]).days)
    return f"{cam}: {len(t)} frames over {(t[-1]-t[0]).days} days, {len(folds)} folds ({time.time()-t0:.0f}s)"


def summarise(cams: list[str]):
    rows = []
    for cam in cams:
        p = DATA / "derived" / cam / "tune_cv.npz"
        if not p.exists():
            continue
        z = np.load(p)
        h, rng = z["h"], max(float(z["p95"] - z["p5"]), 1e-6)
        for key, pred, nr in zip(z["keys"], z["P"], z["nroi"]):
            ok = np.isfinite(pred)
            if not ok.any():
                continue
            mae = float(np.mean(np.abs(pred[ok] - h[ok])))
            bs, thr, lam, sm = key.split("|")
            rows.append({"cam_id": cam, "bs": int(bs), "thr": float(thr), "lam": float(lam), "smooth": sm,
                         "n_oof": int(ok.sum()), "n_folds": len(set(z["fold"][ok])), "span_days": int(z["span_days"]),
                         "roi_median": float(nr), "mae": mae, "nmae": mae / rng, "p1": (mae <= 0.25) or (mae / rng <= 0.10)})
    df = pd.DataFrame(rows)
    out = ROOT / "results" / "scene"
    out.mkdir(parents=True, exist_ok=True)
    df.round(4).to_csv(out / "tune_cv_sites.csv", index=False)
    agg = (df.groupby(["bs", "thr", "lam", "smooth"])
             .agg(sites=("cam_id", "nunique"), p1_sites=("p1", "sum"), median_nmae=("nmae", "median"), median_mae=("mae", "median"))
             .reset_index().sort_values(["p1_sites", "median_nmae", "median_mae"], ascending=[False, True, True]))
    agg.round(4).to_csv(out / "tune_cv_summary.csv", index=False)
    print(agg.head(12).to_string(index=False))
    best = agg.iloc[0]
    print(f"\nselected: bs={int(best.bs)} thr={best.thr} lam={best.lam} smooth={best.smooth} "
          f"(P1 on OOF at {int(best.p1_sites)}/{int(best.sites)} sites, median nMAE {best.median_nmae:.3f})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", type=Path, default=DATA / "sites" / "kill_test.yaml")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--summarise", action="store_true")
    a = ap.parse_args()
    cams = [s["cam_id"] for s in yaml.safe_load(a.sites.read_text(encoding="utf-8"))["sites"]
            if not a.only or s["cam_id"] in a.only]
    if a.summarise:
        return summarise(cams)
    n = 0
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(tune_site, c): c for c in cams}
        for fu in as_completed(futs):
            n += 1
            p = os.environ.get("WORKERQ_PROGRESS")
            if p:
                Path(p).write_text(f"{n / len(cams):.4f}")
            try:
                print(fu.result(), flush=True)
            except Exception:
                print(f"{futs[fu]}: ERROR\n{traceback.format_exc()}", flush=True)
    summarise(cams)


if __name__ == "__main__":
    main()
