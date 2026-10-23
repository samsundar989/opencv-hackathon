"""Head-to-head at Hancock NY (USGS 01421500) on the two floods StageSight reports (SPRINT_W3 §4b.1).

For each event window the scene model is refit with the frozen D-0007 setting (block 4, ROI reliability
≥ 0.80, ridge λ 1, Kalman) on all calibration frames **except ±7 days around the window** (leave-event-out),
exactly as `scripts/scene_score.py` fits the final model, and scored on the window's registered daylight
frames against the USGS gauge.

Windows (ours; StageSight's exact frame sets are not published in a form we can reproduce):
  jul29: 2026-07-29 00Z – 2026-07-31 00Z     sep04: 2026-09-04 00Z – 2026-09-06 00Z

Also reported: the calibration stage range left after the exclusion (the model cannot extrapolate above it),
flood-state recall (camera above the calibration p90 when the gauge is), and the median Kalman σ.

Metrics: RMSE with a frame bootstrap 95 % CI (B = 2000, seed 20261015), MAE, max error, within 0.5 ft,
and coverage = frames with a stage estimate over (a) the hours of the window, (b) frames NIMS listed in
it, (c) daylight frames listed. Baselines that need no camera: calibration median, and the gauge's value
at the window start held through the window (a gauge outage at the start of the event).

Outputs: results/headtohead_hancock/{metrics.csv, pred_<event>.csv}

    python report/headtohead_hancock.py
"""
from __future__ import annotations

import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from riversight.calib.flood_height_map import fit_thr  # noqa: E402
from riversight.calib.scene_regressor import kalman_1d, kalman_params  # noqa: E402
from riversight.killtest import sun_elevation_deg  # noqa: E402
from scene_tune import DATA, _eig_ridge, gauge_series, load_train  # noqa: E402

CAM = "NY_East_Branch_Delaware_River_at_Hancock_Staff"
LAT, LON = 41.95703, -75.28036     # overwritten from kill_test.yaml below
EVENTS = {"jul29": ("2026-07-29T00:00:00Z", "2026-07-31T00:00:00Z"),
          "sep04": ("2026-09-04T00:00:00Z", "2026-09-06T00:00:00Z")}
EXCLUDE = pd.Timedelta("7D")
B, SEED = 2000, 20261015
OUT = ROOT / "results" / "headtohead_hancock"


def frame_time(name: str) -> pd.Timestamp:
    d, t = Path(name).stem.split("___")[1].split("T")
    return pd.Timestamp(f"{d}T{t.replace('-', ':')}")


def gauge_at(g: pd.Series, t: pd.DatetimeIndex, tol: str = "30min") -> np.ndarray:
    s = g.sort_index()
    idx = s.index.get_indexer(t, method="nearest", tolerance=pd.Timedelta(tol))
    return np.where(idx >= 0, s.values[np.clip(idx, 0, None)], np.nan)


def rmse_ci(err: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    reps = [np.sqrt(np.mean(err[rng.integers(0, len(err), len(err))] ** 2)) for _ in range(B)]
    return tuple(float(x) for x in np.percentile(reps, [2.5, 97.5]))


def main() -> None:
    import yaml
    cfg = json.loads((ROOT / "results" / "scene" / "frozen_config.json").read_text(encoding="utf-8"))
    site = next(s for s in yaml.safe_load((DATA / "sites" / "kill_test.yaml").read_text(encoding="utf-8"))["sites"]
                if s["cam_id"] == CAM)
    lat, lon = float(site["lat"]), float(site["lng"])

    t_all, h_all, F_all = load_train(CAM)
    hist = np.load(DATA / "derived" / CAM / "scene_history_all.npz")
    t_hist = pd.to_datetime(hist["t"], utc=True)
    g_full = gauge_series(CAM)
    listed = pd.DatetimeIndex([frame_time(n) for n in
                               (DATA / "derived" / CAM / "history" / "list.txt").read_text().split()])
    rng = np.random.default_rng(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for ev, (a, b) in EVENTS.items():
        a, b = pd.Timestamp(a), pd.Timestamp(b)
        keep = (t_all < a - EXCLUDE) | (t_all >= b + EXCLUDE)
        t_tr, h_tr, X_tr = t_all[keep], h_all[keep], F_all[keep].astype(np.float32)
        te = (t_hist >= a) & (t_hist < b)
        t_te = t_hist[te]
        X_te = hist["F"][te].astype(np.float32)
        truth = gauge_at(g_full, t_te)

        M = fit_thr(X_tr, h_tr)
        roi = M.acc >= cfg["thr"]
        if roi.sum() < cfg["min_roi"]:
            roi = np.ones_like(roi)
        solve = _eig_ridge(X_tr[:, roi].reshape(len(X_tr), -1), X_te[:, roi].reshape(len(X_te), -1), h_tr)
        raw, loo = solve(cfg["lam"])
        g_tr = g_full[(g_full.index < a - EXCLUDE) | (g_full.index >= b + EXCLUDE)]
        q, _ = kalman_params(g_tr.index, g_tr.values, np.zeros(4))
        rho = np.corrcoef(loo[:-1], loo[1:])[0, 1]
        r = max(float(np.var(loo)) * (1 - np.clip(rho, 0, 0.95)), 1e-6)
        cam, sig = kalman_1d(t_te, raw, q, r)

        ok = np.isfinite(cam) & np.isfinite(truth)
        err = cam[ok] - truth[ok]
        lo, hi = rmse_ci(err, rng)
        med = float(np.median(h_tr))
        g0 = gauge_at(g_full, pd.DatetimeIndex([a]), "2h")[0]
        lw = listed[(listed >= a) & (listed < b)]
        lw_day = sun_elevation_deg(lat, lon, pd.Series(lw)) >= -3.0
        hours = int((b - a) / pd.Timedelta("1h"))
        p90 = float(np.quantile(h_tr, 0.90))
        above = truth[ok] > p90
        rows.append({
            "event": ev, "window_start": a, "window_end": b, "train_frames": int(keep.sum()),
            "excluded_frames": int((~keep).sum()), "n_roi": int(roi.sum()), "n": int(ok.sum()),
            "gauge_min_ft": float(np.nanmin(truth)), "gauge_max_ft": float(np.nanmax(truth)),
            "rmse": float(np.sqrt(np.mean(err ** 2))), "rmse_lo": lo, "rmse_hi": hi,
            "mae": float(np.mean(np.abs(err))), "max_abs_err": float(np.max(np.abs(err))),
            "within_0p5ft": float(np.mean(np.abs(err) <= 0.5)),
            "rmse_raw_unsmoothed": float(np.sqrt(np.nanmean((raw[ok] - truth[ok]) ** 2))),
            "rmse_const_median": float(np.sqrt(np.mean((med - truth[ok]) ** 2))),
            "rmse_gauge_held_from_start": float(np.sqrt(np.mean((g0 - truth[ok]) ** 2))),
            "cal_max_ft": float(np.max(h_tr)), "cal_p90_ft": p90,
            "frames_above_cal_max": int(np.sum(truth[ok] > np.max(h_tr))),
            "flood_state_recall": float(np.mean(cam[ok][above] > p90)) if above.any() else float("nan"),
            "median_kalman_sigma_ft": float(np.nanmedian(sig[ok])),
            "window_hours": hours, "listed_frames": len(lw), "listed_daylight_frames": int(lw_day.sum()),
            "cov_pct_hours": 100 * ok.sum() / hours, "cov_pct_listed": 100 * ok.sum() / max(len(lw), 1),
            "cov_pct_listed_daylight": 100 * ok.sum() / max(int(lw_day.sum()), 1),
        })
        pd.DataFrame({"time": t_te, "gauge_ft": truth, "camera_ft": cam, "sigma_ft": sig, "raw_ft": raw}) \
            .to_csv(OUT / f"pred_{ev}.csv", index=False, float_format="%.4f")
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "metrics.csv", index=False, float_format="%.4f")
    print(df.T.to_string())


if __name__ == "__main__":
    main()
