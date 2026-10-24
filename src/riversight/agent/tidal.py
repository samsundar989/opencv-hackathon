"""Tidal sites: a daily tide must never raise a flood alert (D-0013 W2-1).

First Mallard Branch is a tidal slough with ~4 ft daily tides; on Oct 23 the live agent drafted a flood alert on an
ordinary high tide ("rising +0.33 ft/h at 28.82 ft, site p90 28.04") and it was approved — a documented false alert.

Detection: least-squares harmonic fit of the main tidal constituents (M2 12.42 h, S2 12.00 h, K1 23.93 h, O1 25.82 h)
plus a linear trend to hourly gauge data. A site is tidal when the harmonics explain ≥ TIDAL_R2 of the variance
of the detrended series, with the semidiurnal M2/S2 part alone ≥ SEMI_R2, in most analysis windows. Rivers have no energy at these periods (daily snowmelt or
hydropeaking cycles are ~24 h only, so they fail the semidiurnal M2/S2 test).

Flood logic for a tidal site: the 3 h rise and the stage percentile mean nothing (half the day is "rising", every
spring tide tops the p90). What matters is the **tide-free residual** — observed stage minus the harmonic prediction
from the previous days — and how today's high water compares with the site's own distribution of daily maxima.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PERIODS_H = {"M2": 12.4206, "S2": 12.0, "K1": 23.9345, "O1": 25.8193}
TIDAL_R2 = 0.5            # share of detrended variance explained by the tidal harmonics
SEMI_R2 = 0.25            # ... of which the semidiurnal M2/S2 alone must explain this much (a daily river cycle has none)
MIN_HOURS = 72            # a fit needs at least 3 days of hourly data
SURGE_FT = 0.5            # a residual this far above the predicted tide is non-tidal water (surge / river flood)
SURGE_SD = 3.0            # ... or this many residual standard deviations


def _hourly(g: pd.Series) -> pd.Series:
    h = g.sort_index().resample("1h").mean()
    return h.interpolate(limit=3).dropna()


def _design(t_hours: np.ndarray) -> np.ndarray:
    cols = [np.ones_like(t_hours), t_hours / 24.0]
    for p in PERIODS_H.values():
        w = 2 * np.pi * t_hours / p
        cols += [np.cos(w), np.sin(w)]
    return np.column_stack(cols)


def fit(g: pd.Series) -> dict | None:
    """Harmonic fit on a gauge series → {coef, t0, r2_tidal, resid_sd} or None if too short."""
    h = _hourly(g)
    if len(h) < MIN_HOURS:
        return None
    t0 = h.index[0]
    th = ((h.index - t0).total_seconds() / 3600.0).to_numpy()
    X, y = _design(th), h.to_numpy(float)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    trend = X[:, :2] @ coef[:2]
    detr = y - trend
    tide = X[:, 2:] @ coef[2:]
    semi = X[:, 2:6] @ coef[2:6]                     # M2 + S2 only: rivers have no twice-daily cycle
    resid = y - X @ coef
    var = float(np.var(detr))
    r2 = 1.0 - float(np.var(resid)) / var if var > 1e-9 else 0.0
    r2_semi = float(np.var(semi)) / var if var > 1e-9 else 0.0
    return {"coef": coef, "t0": t0, "r2_tidal": r2, "r2_semidiurnal": r2_semi, "resid_sd": float(np.std(resid)),
            "amp_ft": float(np.ptp(tide)) / 2}


def predict(model: dict, when) -> float:
    th = (pd.DatetimeIndex([when]) - model["t0"]).total_seconds().to_numpy() / 3600.0
    return float((_design(th) @ model["coef"])[0])


def detect(g: pd.Series, window_days: int = 14, step_days: int = 7) -> dict:
    """Is this gauge tidal? Fits over sliding windows of the history; tidal when most windows reach TIDAL_R2."""
    g = g.dropna().sort_index()
    if len(g) < 2:
        return {"tidal": False, "windows": 0, "median_r2": None}
    r2s, amps = [], []
    t = g.index[0]
    while t + pd.Timedelta(days=window_days) <= g.index[-1]:
        m = fit(g[(g.index >= t) & (g.index < t + pd.Timedelta(days=window_days))])
        if m:
            r2s.append(m["r2_tidal"] if m["r2_semidiurnal"] >= SEMI_R2 else 0.0)
            amps.append(m["amp_ft"])
        t += pd.Timedelta(days=step_days)
    if not r2s:
        m = fit(g)
        r2s, amps = ([m["r2_tidal"] if m["r2_semidiurnal"] >= SEMI_R2 else 0.0], [m["amp_ft"]]) if m else ([], [])
    if not r2s:
        return {"tidal": False, "windows": 0, "median_r2": None}
    med = float(np.median(r2s))
    share = float(np.mean(np.array(r2s) >= TIDAL_R2))
    return {"tidal": bool(share >= 0.6), "windows": len(r2s), "median_r2": round(med, 3),
            "share_windows_tidal": round(share, 3), "median_amplitude_ft": round(float(np.median(amps)), 2)}


def daily_max_quantiles(g: pd.Series) -> dict:
    d = g.dropna().resample("1D").max().dropna()
    if not len(d):
        return {}
    return {f"daily_max_p{q}": round(float(d.quantile(q / 100)), 3) for q in (50, 90, 95, 99)}


def residual_quantiles(g: pd.Series, step_h: int = 3) -> dict:
    """Distribution of the 6-h-ahead tide residual over the history (the same causal fit `assess` uses)."""
    g = g.dropna().sort_index()
    pts = g.resample("1h").last().dropna().index[24 * 8::step_h]
    res = []
    for t in pts:
        w = g[(g.index > t - pd.Timedelta("7D")) & (g.index <= t)]
        m = fit(w[w.index < t - pd.Timedelta(hours=6)])
        if m is not None:
            res.append(float(w.iloc[-1]) - predict(m, w.index[-1]))
    if not res:
        return {}
    r = np.array(res)
    return {"resid_p95": round(float(np.percentile(r, 95)), 3), "resid_p99": round(float(np.percentile(r, 99)), 3),
            "resid_n": len(r)}


def assess(g_recent: pd.Series, now, daily_max: dict | None = None) -> dict:
    """Tidal reading of the last days of gauge data at `now`: predicted tide, residual, and a verdict.

    `g_recent` should hold ≥ 3 days before `now` (the get_gauge window is 7 days for tidal sites). The model is fit on
    data strictly before the last 6 h, so a surge building right now shows up in the residual instead of being fitted."""
    g = g_recent.dropna().sort_index()
    g = g[g.index <= pd.Timestamp(now)]
    if not len(g):
        return {"ok": False, "summary": "no gauge data for the tidal check"}
    m = fit(g[g.index < pd.Timestamp(now) - pd.Timedelta(hours=6)])
    if m is None:
        return {"ok": False, "summary": "too little gauge history for a tidal fit"}
    obs = float(g.iloc[-1])
    pred = predict(m, g.index[-1])
    resid = obs - pred
    dm = daily_max or {}
    # site-calibrated: the residual must exceed the site's own 99th-percentile residual (spring/neap modulation, river
    # flow and wind make a generic 3σ fire every few days) AND the water must be high for the site (≥ daily-max p90);
    # or the water is a record-level high (≥ daily-max p99) whatever the model says
    thr = max(SURGE_FT, SURGE_SD * m["resid_sd"], float(dm.get("resid_p99") or 0.0))
    high = dm.get("daily_max_p90") is None or obs >= dm["daily_max_p90"]
    above_envelope = bool(dm.get("daily_max_p99") is not None and obs >= dm["daily_max_p99"])
    non_tidal = bool((resid >= thr and high) or above_envelope)
    return {"ok": True, "observed_ft": round(obs, 3), "predicted_tide_ft": round(pred, 3), "residual_ft": round(resid, 3),
            "surge_threshold_ft": round(thr, 3), "above_daily_max_p99": above_envelope, "non_tidal_rise": non_tidal,
            "tidal_r2": round(m["r2_tidal"], 3),
            "summary": (f"tidal site: observed {obs:.2f} ft vs predicted tide {pred:.2f} ft (residual {resid:+.2f} ft, "
                        f"threshold {thr:.2f})" + ("; ABOVE the site's daily-max p99" if above_envelope else "")
                        + (" -> water above the tide (surge/flood)" if non_tidal else " -> ordinary tide"))}
