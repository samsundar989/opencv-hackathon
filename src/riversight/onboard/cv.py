"""Forward-chaining monthly CV with the frozen D-0007 setting only (no grid, no per-site tuning — D-0010 §3).

Same folds and maths as scripts/scene_tune.py (train before month M − 7 days, test on M; ≥ 150 training frames
over ≥ 30 days, ≥ 20 test frames; flood-height ROI at reliability ≥ thr, kernel ridge λ, causal Kalman), imported
from it so the two cannot drift. Writes data/derived/<cam>/tune_cv.npz with the single frozen key, which is the
layout scripts/export_site_models.py reads σ from.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
FROZEN = ROOT / "results" / "scene" / "frozen_config.json"


def frozen_cfg() -> dict:
    return json.loads(FROZEN.read_text(encoding="utf-8"))


def frozen_key(cfg: dict) -> str:
    return f"{cfg['bs']}|{cfg['thr']}|{cfg['lam']}|{cfg['smooth']}"


def _scene_tune(cut: pd.Timestamp):
    sys.path.insert(0, str(ROOT / "scripts"))
    import scene_tune
    scene_tune.CUT = cut                     # calibration cut = end of the onboarding window
    return scene_tune


def predict_fold(X_tr, h_tr, t_tr_end, X_te, t_te, g: pd.Series, cfg: dict) -> np.ndarray:
    """Frozen-setting prediction for one train/test split (block size 4 features)."""
    from riversight.calib.flood_height_map import fit_thr
    from riversight.calib.scene_regressor import causal_median, kalman_1d, kalman_params
    st = sys.modules["scene_tune"]
    M = fit_thr(X_tr, h_tr)
    roi = M.acc >= cfg["thr"]
    if roi.sum() < cfg["min_roi"]:
        roi = np.ones_like(roi)
    solve = st._eig_ridge(X_tr[:, roi].reshape(len(X_tr), -1), X_te[:, roi].reshape(len(X_te), -1), h_tr)
    p, loo = solve(cfg["lam"])
    if cfg["smooth"] == "kalman":
        gg = g[g.index < t_tr_end]
        q, _ = kalman_params(gg.index, gg.values, np.zeros(4))
        rho = np.corrcoef(loo[:-1], loo[1:])[0, 1] if len(loo) > 2 else 0.0
        r = float(np.var(loo)) * (1 - np.clip(np.nan_to_num(rho), 0, 0.95))
        return kalman_1d(t_te, p, q, max(r, 1e-6))[0]
    return causal_median(t_te, p, "3h")


def frozen_cv(data: Path, cam: str, cut: pd.Timestamp, cfg: dict | None = None, write: bool = True) -> dict | None:
    """OOF predictions for the frozen setting. Returns dict(t, h, oof, fold, n_folds) or None."""
    cfg = cfg or frozen_cfg()
    if cfg["bs"] != 4:
        raise NotImplementedError("frozen setting uses 4 px blocks")
    st = _scene_tune(cut)
    L = st.load_train(cam, data)
    if L is None or len(L[0]) < 200:
        return None
    t, h, F16 = L
    folds = st.month_folds(t)
    if not folds:
        return None
    g = st.gauge_series(cam)
    X = F16.astype(np.float32)
    oof = np.full(len(h), np.nan)
    fold_id = np.full(len(h), "", dtype=object)
    for name, tr, te in folds:
        fold_id[te] = name
        oof[te] = predict_fold(X[tr], h[tr], t[tr][-1], X[te], t[te], g, cfg)
    if write:
        np.savez_compressed(data / "derived" / cam / "tune_cv.npz", t=t.asi8, h=h, fold=fold_id.astype(str),
                            keys=np.array([frozen_key(cfg)]), P=oof[None], nroi=np.array([np.nan]),
                            p5=np.quantile(h, 0.05), p95=np.quantile(h, 0.95), span_days=(t[-1] - t[0]).days,
                            source=np.array("onboard frozen-setting CV"))
    return {"t": t, "h": h, "oof": oof, "fold": fold_id, "n_folds": len(folds), "g": g}


def fewshot(data: Path, cam: str, cut: pd.Timestamp, days: tuple[int, ...], test_months: int = 2,
            cfg: dict | None = None, gap: pd.Timedelta = pd.Timedelta("7D"), min_train: int = 20) -> list[dict]:
    """Calibration-length curve. Test set = the site's last `test_months` calendar months with ≥ 20 frames
    (identical for every N). For test month M, train on frames in [M − gap − N days, M − gap)."""
    cfg = cfg or frozen_cfg()
    st = _scene_tune(cut)
    L = st.load_train(cam, data)
    if L is None:
        return []
    t, h, F16 = L
    g = st.gauge_series(cam)
    X = F16.astype(np.float32)
    def full(m):                             # ≥ 20 frames spread over ≥ 14 days (drops a 2-day tail month)
        tm = t[(t >= m) & (t < m + pd.offsets.MonthBegin(1))]
        return len(tm) >= 20 and (tm[-1] - tm[0]).days >= 14
    months = [m for m in pd.date_range(t[0].floor("D").replace(day=1), t[-1], freq="MS") if full(m)][-test_months:]
    rows = []
    for n in days:
        err, cover, ntr = [], [], []
        for m in months:
            te = (t >= m) & (t < m + pd.offsets.MonthBegin(1))
            tr = (t < m - gap) & (t >= m - gap - pd.Timedelta(days=n))
            ntr.append(int(tr.sum()))
            if tr.sum() < min_train or np.ptp(h[tr]) < 0.05:
                cover.append(0)
                continue
            p = predict_fold(X[tr], h[tr], t[tr][-1], X[te], t[te], g, cfg)
            err.append(np.abs(p - h[te]))
            cover.append(1)
        e = np.concatenate(err) if err else np.array([])
        rng = max(float(np.quantile(h, 0.95) - np.quantile(h, 0.05)), 1e-6)
        rows.append({"cam_id": cam, "days": n, "test_months": "|".join(m.strftime("%Y-%m") for m in months),
                     "n_test": int(e.size), "months_scored": int(sum(cover)), "n_train_median": float(np.median(ntr)) if ntr else 0,
                     "mae": float(e.mean()) if e.size else np.nan, "median_ae": float(np.median(e)) if e.size else np.nan,
                     "nmae": float(e.mean() / rng) if e.size else np.nan})
    return rows
