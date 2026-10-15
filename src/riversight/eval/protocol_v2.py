"""Kill-test protocol v2 (pre-registered in D-0006): per-site metrics and the PASS / partial / FAIL verdict.

Pass/fail criteria
  P1 accuracy  per site: MAE ≤ 0.25 ft or nMAE (MAE ÷ calibration p95−p5) ≤ 10 %; need ≥ 10/20 sites.
  P2 value     per site with event frames (|Δstage over 24 h| ≥ 0.25 ft): camera MAE on event frames
               < 24 h last-known-value MAE on the same frames; need ≥ 70 % of those sites.
  P3 registration ≥ 90 % of daylight frames.
  PASS = P1 ∧ P2 ∧ P3;  FAIL = (P1 sites < 6) ∧ ¬P2;  otherwise partial.

Reported, not pass/fail: all-frame MAE vs 15 min / 24 h persistence and constant (calibration) median;
outage gap-fill vs last-known value at 6 h / 24 h / 72 h / 7 d; flood-state balanced accuracy
(stage > calibration p90); Spearman ρ; tier.

A site with no camera prediction counts as failing P1 (and P2 if it has events). Nothing is dropped.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MAE_FT = 0.25
NMAE = 0.10
EVENT_FT = 0.25
MIN_EVENT_FRAMES = 3          # a site "has events" when ≥ this many scored frames are event frames
P1_SITES = 10
P1_FAIL_BELOW = 6
P2_FRAC = 0.70
P3_RATE = 0.90
GAPS = {"6h": "6h", "24h": "24h", "72h": "72h", "7d": "7D"}


def last_known(t: pd.DatetimeIndex, gauge: pd.Series, lag: str, tol: str = "1h") -> np.ndarray:
    """Gauge value last reported at or before t − lag (within `tol` of it): the value a user would
    have if the gauge went offline `lag` ago."""
    g = gauge.dropna().sort_index()
    q = pd.DataFrame({"tq": pd.DatetimeIndex(t) - pd.Timedelta(lag)})
    q["order"] = np.arange(len(q))
    s = pd.DataFrame({"tg": g.index, "v": g.values})
    m = pd.merge_asof(q.sort_values("tq"), s, left_on="tq", right_on="tg", direction="backward",
                      tolerance=pd.Timedelta(tol))
    return m.sort_values("order")["v"].to_numpy(float)


def _mae(p, h, m=None):
    ok = np.isfinite(p) & np.isfinite(h)
    if m is not None:
        ok &= m
    return float(np.mean(np.abs(p[ok] - h[ok]))) if ok.any() else float("nan")


def _bacc(pred_state, true_state, valid):
    pos, neg = valid & true_state, valid & ~true_state
    if pos.sum() < 3 or neg.sum() < 3:
        return float("nan")
    return float(0.5 * (pred_state[pos].mean() + (~pred_state[neg]).mean()))


def site_metrics(t: pd.DatetimeIndex, cam: np.ndarray, h: np.ndarray, gauge: pd.Series,
                 calib_stage: np.ndarray, reg_rate: float = float("nan"), tier: str = "B") -> dict:
    """t, cam, h: scored frames (daylight, registered), camera estimate, gauge stage at frame time.
    gauge: full gauge series (UTC index) for persistence/last-known lookups. calib_stage: stage values of
    the calibration frames (sets nMAE range, constant median and the flood threshold)."""
    t = pd.DatetimeIndex(t)
    cam, h = np.asarray(cam, float), np.asarray(h, float)
    cs = np.asarray(calib_stage, float)
    cs = cs[np.isfinite(cs)]
    p5, p95, p90, med = (np.quantile(cs, q) for q in (0.05, 0.95, 0.90, 0.5))
    rng = max(p95 - p5, 1e-6)
    p15 = last_known(t, gauge, "15min", "20min")
    p24 = last_known(t, gauge, "24h")
    ev = np.isfinite(p24) & (np.abs(h - p24) >= EVENT_FT)
    mae = _mae(cam, h)
    r = {
        "tier": tier, "n": int(np.isfinite(h).sum()), "n_pred": int((np.isfinite(cam) & np.isfinite(h)).sum()),
        "reg_rate": reg_rate, "calib_p5_p95_ft": float(rng), "test_range_ft": float(np.nanmax(h) - np.nanmin(h)) if len(h) else np.nan,
        "mae": mae, "nmae": mae / rng if np.isfinite(mae) else float("nan"),
        "mae_p15": _mae(p15, h), "mae_p24": _mae(p24, h), "mae_const": _mae(np.full_like(h, med), h),
        "n_ev": int(ev.sum()), "mae_ev": _mae(cam, h, ev), "mae_p24_ev": _mae(p24, h, ev),
        "spearman": float(pd.Series(cam).corr(pd.Series(h), method="spearman")) if np.isfinite(cam).sum() > 2 else float("nan"),
        "bacc_flood": _bacc(cam > p90, h > p90, np.isfinite(cam) & np.isfinite(h)),
        "bacc_flood_p24": _bacc(p24 > p90, h > p90, np.isfinite(p24) & np.isfinite(h)),
        "n_flood": int((h > p90).sum()),
    }
    for k, lag in GAPS.items():
        lk = last_known(t, gauge, lag)
        both = np.isfinite(lk) & np.isfinite(cam)
        r[f"gap_{k}_lkv"] = _mae(lk, h, both)
        r[f"gap_{k}_cam"] = _mae(cam, h, both)
    r["p1"] = bool(np.isfinite(mae) and (mae <= MAE_FT or r["nmae"] <= NMAE))
    r["has_events"] = r["n_ev"] >= MIN_EVENT_FRAMES
    r["p2"] = bool(r["has_events"] and np.isfinite(r["mae_ev"]) and r["mae_ev"] < r["mae_p24_ev"]) if r["has_events"] else None
    return r


def verdict(table: pd.DataFrame, reg_rate_all: float) -> dict:
    """table: one row per site (all 20, including sites without predictions) from site_metrics."""
    n_p1 = int(table["p1"].fillna(False).astype(bool).sum())
    evs = table[table["has_events"].fillna(False).astype(bool)]
    n_ev_sites = len(evs)
    n_p2 = int(evs["p2"].fillna(False).astype(bool).sum())
    P1 = n_p1 >= P1_SITES
    P2 = n_ev_sites > 0 and n_p2 / n_ev_sites >= P2_FRAC
    P3 = reg_rate_all >= P3_RATE
    if P1 and P2 and P3:
        v = "PASS"
    elif n_p1 < P1_FAIL_BELOW and not P2:
        v = "FAIL"
    else:
        v = "PARTIAL"
    return {"verdict": v, "P1": P1, "P1_sites": n_p1, "n_sites": len(table), "P2": P2, "P2_sites": n_p2,
            "P2_event_sites": n_ev_sites, "P2_needs_history_cv": n_ev_sites < 5, "P3": P3, "reg_rate": reg_rate_all}
