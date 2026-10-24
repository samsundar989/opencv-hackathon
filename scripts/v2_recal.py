"""W4 (D-0013 W4-3): online recalibration, evaluated forward in time inside the calibration history (shadow only).

A camera model can't read above the highest stage it was calibrated on (kernel ridge on appearance; the
Hancock 17 ft crest was out of range). Refitting as new daylight frames + gauge arrive extends the range.
This script measures what that buys, with the frozen D-0007 knobs (bs 4, reliability ≥ 0.80, λ = 1, Kalman):

  static    fit once on everything before day 90 of the site's record, never refit
  monthly   refit at every calendar-month start on all earlier frames
  weekly    refit every Monday 00Z on all earlier frames (the proposed online refit)

All three predict exactly the same test frames (from day 90 to 2026-10-03 00Z, the calibration period; no
frozen test day is read). There is no gap: a refit at time T uses only frames before T and predicts frames
after T, which is what an online refit does live. Camera models: v1 (served) and the selected v2.

Reported per site and method: MAE on all test frames; the share of test frames whose gauge stage is above
the method's current training maximum ("out of range"); MAE on the frames above the *static* model's range
(the common subset where recalibration can help); and the number of refits that raised the training maximum.

  scripts/v2_recal.py --jobs 5   → data/derived/<cam>/v2_recal.npz;  --summarise → results/v2/recal_*.csv
"""
from __future__ import annotations

import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")

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
sys.path.insert(0, str(ROOT / "scripts"))
DATA = Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))
OUT = ROOT / "results" / "v2"
WARMUP = pd.Timedelta("90D")
METHODS = ("static", "monthly", "weekly")
THR, LAM, MIN_ROI, MIN_DINO_ROI = 0.80, 1.0, 50, 10


def refit_times(t: pd.DatetimeIndex, method: str) -> list[pd.Timestamp]:
    start = t[0] + WARMUP
    if method == "static":
        return [start]
    freq = "MS" if method == "monthly" else "W-MON"
    ts = [start] + [x for x in pd.date_range(start, t[-1], freq=freq) if x > start]
    return [x for x in ts if (t >= x).any()]


def fit_predict(spec, X, P, t, h, tr, te, Z, q):
    """One fit of a v2_cv spec on frames `tr`, raw + Kalman-smoothed predictions for frames `te`."""
    from riversight.calib import scene_v2 as S
    from riversight.calib.flood_height_map import fit_thr
    from riversight.calib.scene_regressor import kalman_1d
    ntr, nte = int(tr.sum()), int(te.sum())
    Ktr, Kte = 0.0, 0.0
    if spec["v1"] and spec["w"] < 1:
        roi = fit_thr(X[tr], h[tr]).acc >= THR
        roi = roi if roi.sum() >= MIN_ROI else np.ones_like(roi)
        k = S.linear_kernel(X[tr][:, roi].reshape(ntr, -1), X[te][:, roi].reshape(nte, -1))
        Ktr, Kte = Ktr + (1 - spec["w"]) * k[0], Kte + (1 - spec["w"]) * k[1]
    if spec["dino"] == "dino_roi":
        sel = fit_thr(P[tr], h[tr]).acc >= THR
        sel = sel if sel.sum() >= MIN_DINO_ROI else np.ones_like(sel)
        k = S.linear_kernel(P[tr][:, sel].reshape(ntr, -1), P[te][:, sel].reshape(nte, -1))
        Ktr, Kte = Ktr + spec["w"] * k[0], Kte + spec["w"] * k[1]
    p, loo = S.ridge_dual(Ktr, Kte, h[tr], LAM)
    if spec["sun"]:
        p = p + S.nuisance_fit(Z[tr], loo, Z[te])
        loo = loo - S.nuisance_fit(Z[tr], loo, Z[tr])
    return p, kalman_1d(t[te], p, q, S.kalman_r(loo))[0]


def run_site(cam: str, configs: dict) -> str:
    from riversight.calib import scene_v2 as S
    from riversight.calib.scene_regressor import kalman_params
    from riversight.killtest import site_latlng
    from scene_tune import gauge_series
    from v2_cv import load_site, parse
    out = DATA / "derived" / cam / "v2_recal.npz"
    if out.exists():
        return f"{cam}: cached"
    t0 = time.time()
    t, h, F16, P16, _, _ = load_site(cam)
    if t[-1] - t[0] < WARMUP + pd.Timedelta("30D"):
        return f"{cam}: record too short ({(t[-1] - t[0]).days} days)"
    X, P = F16.astype(np.float32), P16.astype(np.float32)
    g = gauge_series(cam)
    lat, lng = site_latlng(DATA, cam)
    Z = S.nuisance_matrix(t, lat, lng, False)
    test = t >= t[0] + WARMUP
    res, trmax, nref = {}, {}, {}
    for model, cfg in configs.items():
        spec = parse(cfg)
        for m in METHODS:
            pred, mx = np.full(len(h), np.nan), np.full(len(h), np.nan)
            ts = refit_times(t, m)
            raised, prev = 0, -np.inf
            for i, T in enumerate(ts):
                tr = t < T
                te = (t >= T) & (t < ts[i + 1]) if i + 1 < len(ts) else (t >= T)
                if tr.sum() < 150 or te.sum() == 0:
                    continue
                q, _ = kalman_params(g[g.index < T].index, g[g.index < T].values, np.zeros(4))
                _, sm = fit_predict(spec, X, P, t, h, tr, te, Z, q)
                pred[te] = sm
                mx[te] = h[tr].max()
                raised += h[tr].max() > prev + 1e-9 and i > 0
                prev = max(prev, h[tr].max())
            res[(model, m)], trmax[(model, m)], nref[(model, m)] = pred, mx, (len(ts), raised)
    keys = list(res)
    np.savez_compressed(out, t=t.asi8, h=h, test=test, keys=np.array([f"{a}|{b}" for a, b in keys]),
                        P=np.stack([res[k] for k in keys]), MX=np.stack([trmax[k] for k in keys]),
                        NREF=np.array([nref[k] for k in keys]))
    return f"{cam}: {int(test.sum())} test frames ({time.time() - t0:.0f}s)"


def summarise(cams: list[str]):
    rows = []
    for cam in cams:
        p = DATA / "derived" / cam / "v2_recal.npz"
        if not p.exists():
            continue
        z = np.load(p)
        h, test = z["h"], z["test"]
        keys = list(z["keys"])
        for model in sorted({k.split("|")[0] for k in keys}):
            st_mx = z["MX"][keys.index(f"{model}|static")]
            common = test & np.all([np.isfinite(z["P"][keys.index(f"{model}|{m}")]) for m in METHODS], 0)
            above = common & (h > st_mx)
            for m in METHODS:
                k = keys.index(f"{model}|{m}")
                e = np.abs(z["P"][k] - h)
                rows.append({"cam_id": cam, "model": model, "method": m, "n_test": int(common.sum()),
                             "mae": float(e[common].mean()), "n_above_static_range": int(above.sum()),
                             "mae_above_static_range": float(e[above].mean()) if above.any() else np.nan,
                             "share_out_of_own_range": float((h[common] > z["MX"][k][common]).mean()),
                             "refits": int(z["NREF"][k][0]), "refits_raising_max": int(z["NREF"][k][1])})
    df = pd.DataFrame(rows)
    if df.empty:
        print("no sites yet")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    df.round(4).to_csv(OUT / "recal_sites.csv", index=False)
    agg = (df.groupby(["model", "method"], sort=False)
             .agg(sites=("cam_id", "nunique"), test_frames=("n_test", "sum"), median_mae=("mae", "median"),
                  mean_mae=("mae", "mean"), sites_with_above_range=("n_above_static_range", lambda x: int((x > 0).sum())),
                  frames_above_static_range=("n_above_static_range", "sum"),
                  median_mae_above_static_range=("mae_above_static_range", "median"),
                  median_share_out_of_own_range=("share_out_of_own_range", "median"),
                  mean_share_out_of_own_range=("share_out_of_own_range", "mean"))
             .reset_index())
    agg.round(4).to_csv(OUT / "recal_summary.csv", index=False)
    print(agg.round(3).to_string(index=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", type=Path, default=DATA / "sites" / "kill_test.yaml")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--summarise", action="store_true")
    a = ap.parse_args()
    cams = [s["cam_id"] for s in yaml.safe_load(a.sites.read_text(encoding="utf-8"))["sites"]
            if not a.only or s["cam_id"] in a.only]
    if a.summarise:
        return summarise(cams)
    summ = pd.read_csv(OUT / "cv_summary.csv")
    configs = {"v1": "v1", "v2": summ.loc[summ["selected"], "config"].iloc[0]}
    n = 0
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(run_site, c, configs): c for c in cams}
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
