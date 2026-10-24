"""W4 (D-0013 W4-2): score the fused stage on simulated gauge outages over the calibration history.

Camera readings are the **out-of-fold raw predictions** of the D-0007 forward-chaining CV (data/derived/<cam>/
v2_cv.npz, before any smoothing), so every camera number used here came from a model that never saw that
month. Gauge truth is the USGS series (t < 2026-10-03, the calibration period; no frozen test day is read).

Outages: at every site, starts every 37 h (the time of day drifts) from the start of the site's second CV
fold to CUT − L, for L ∈ {6 h, 24 h, 72 h, 7 d}. During an outage the methods see no gauge:
  lkv          last gauge value before the outage (the baseline a user has today)
  camera       camera-only causal Kalman over the outage frames (the D-0007 smoother, restarted at the outage)
  fused        Fused filter: starts at the last gauge value, camera updates, no offset anchoring
  fused_bias   Fused filter with the camera−gauge offset anchored over the 48 h before the outage
               (**primary**, fixed in this docstring before any result)
Each method uses only information before the outage start (q from the gauge record and r from raw residuals
before the start's calendar month; the anchor from the 48 h before) plus the outage's own camera frames.
Scored hourly over the outage (night included: at night the filter holds its last estimate and σ grows),
against the gauge reading within ±20 min. Camera models: v1 (D-0007, served) and the selected v2.

  python scripts/v2_fusion.py   → results/v2/fusion_sites.csv, fusion_summary.csv, fusion.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from riversight.calib.fusion import Fused, anchor_bias, camera_r  # noqa: E402
from riversight.calib.scene_regressor import kalman_1d  # noqa: E402
from scene_tune import CUT, DATA, gauge_series  # noqa: E402

OUT = ROOT / "results" / "v2"
GAPS = {"6h": 6, "24h": 24, "72h": 72, "7d": 168}
STEP = pd.Timedelta("37h")
MODELS = {"v1": "v1", "v2": None}          # v2 = the selected config in cv_summary.csv
MOVING_FT = 0.25


def hourly_q(g: pd.Series) -> float:
    dh = np.diff(g.resample("1h").median().dropna().values)
    return max(float(np.var(dh)) if len(dh) > 2 else 1e-3, 1e-6)


def simulate_site(cam: str, cfg: str) -> list[dict]:
    z = np.load(DATA / "derived" / cam / "v2_cv.npz")
    k = list(z["configs"]).index(cfg)
    t = pd.DatetimeIndex(pd.to_datetime(z["t"], utc=True)).as_unit("ns")
    h, raw, fold = z["h"], z["R"][k], z["fold"]
    folds = sorted(f for f in set(fold) if f)
    if len(folds) < 2:
        return []
    g = gauge_series(cam).dropna()
    g = g[~g.index.duplicated()]
    gi = g.index
    t_unix = t.asi8 / 1e9
    rows, cache = [], {}
    first = pd.Timestamp(folds[1] + "-01", tz="UTC")
    for name, L in GAPS.items():
        dur = pd.Timedelta(hours=L)
        s0 = first
        while s0 + dur <= CUT:
            j = gi.searchsorted(s0, "right") - 1
            if j < 0 or (s0 - gi[j]) > pd.Timedelta("20min"):
                s0 += STEP
                continue
            g0 = float(g.iloc[j])
            m0 = s0.floor("D").replace(day=1)               # q and r from data before the start's month
            if m0 not in cache:
                prior = (t < m0) & np.isfinite(raw) & (fold != "")
                cache[m0] = (camera_r(raw[prior] - h[prior]), hourly_q(g[gi < m0]))
            r, q = cache[m0]
            inside = np.flatnonzero((t > s0) & (t <= s0 + dur))
            evals = pd.date_range(s0 + pd.Timedelta("1h"), s0 + dur, freq="1h").as_unit("ns")   # same unit as t
            ge = g.reindex(evals, method="nearest", tolerance=pd.Timedelta("20min")).values
            if not np.isfinite(r) or np.isfinite(ge).sum() == 0:
                s0 += STEP
                continue
            zin = raw[inside]
            cam_s = kalman_1d(t[inside], zin, q, r)[0] if len(inside) else np.array([])
            est = {}
            for meth, anchor in (("fused", False), ("fused_bias", True)):
                F = Fused().gauge(s0.timestamp(), g0)
                if anchor:
                    F.b = anchor_bias(t, raw, h, s0)
                xs, ss, ci = [], [], 0
                for te in evals:
                    while ci < len(inside) and t[inside[ci]] <= te:
                        F.camera(t_unix[inside[ci]], zin[ci], r, q)
                        ci += 1
                    F.predict(te.timestamp(), q)
                    xs.append(F.x)
                    ss.append(F.sigma)
                est[meth] = (np.array(xs), np.array(ss))
            # camera-only: the latest smoothed camera value at or before each eval hour (NaN before the first frame)
            pos = np.searchsorted(t[inside].asi8, evals.asi8, "right") - 1
            cam_e = np.where(pos >= 0, cam_s[np.clip(pos, 0, None)] if len(cam_s) else np.nan, np.nan)
            ok = np.isfinite(ge)
            rows.append({"cam_id": cam, "gap": name, "start": s0, "n_eval": int(ok.sum()), "n_frames": len(inside),
                         "move_ft": float(np.nanmax(np.abs(ge - g0))),
                         **{f"err_{m}": e for m, e in (("lkv", np.abs(g0 - ge)), ("camera", np.abs(cam_e - ge)),
                                                       ("fused", np.abs(est["fused"][0] - ge)),
                                                       ("fused_bias", np.abs(est["fused_bias"][0] - ge)))},
                         "z_fused_bias": (est["fused_bias"][0] - ge) / est["fused_bias"][1], "lkv_err_raw": np.abs(g0 - ge)})
            s0 += STEP
    return rows


def main():
    summ = pd.read_csv(OUT / "cv_summary.csv")
    MODELS["v2"] = summ.loc[summ["selected"], "config"].iloc[0]
    cams = [s["cam_id"] for s in yaml.safe_load((DATA / "sites" / "kill_test.yaml").read_text(encoding="utf-8"))["sites"]]
    site_rows = []
    meths = ("lkv", "camera", "fused", "fused_bias")
    for model, cfg in MODELS.items():
        for cam in cams:
            for o in simulate_site(cam, cfg):
                lk = o["lkv_err_raw"]
                ok = np.isfinite(lk)
                mv = ok & (lk >= MOVING_FT)
                for m in meths:
                    e = o[f"err_{m}"]
                    site_rows.append({"model": model, "cam_id": cam, "gap": o["gap"], "start": o["start"], "method": m,
                                      "sum_ae": float(np.nansum(e[ok])), "n": int(np.isfinite(e[ok]).sum()),
                                      "sum_ae_moving": float(np.nansum(e[mv])), "n_moving": int(np.isfinite(e[mv]).sum()),
                                      "within_2sigma": float(np.nanmean(np.abs(o["z_fused_bias"][ok]) <= 2)) if m == "fused_bias" else np.nan,
                                      "n_frames": o["n_frames"], "move_ft": o["move_ft"]})
        print(model, cfg, "done", flush=True)
    d = pd.DataFrame(site_rows)
    per_site = (d.groupby(["model", "gap", "method", "cam_id"])
                  .agg(outages=("start", "nunique"), n=("n", "sum"), sum_ae=("sum_ae", "sum"),
                       n_moving=("n_moving", "sum"), sum_ae_moving=("sum_ae_moving", "sum"),
                       within_2sigma=("within_2sigma", "mean")).reset_index())
    per_site["mae"] = per_site["sum_ae"] / per_site["n"]
    per_site["mae_moving"] = per_site["sum_ae_moving"] / per_site["n_moving"].replace(0, np.nan)
    OUT.mkdir(parents=True, exist_ok=True)
    per_site.round(4).to_csv(OUT / "fusion_sites.csv", index=False)
    lk = per_site[per_site.method == "lkv"].set_index(["model", "gap", "cam_id"])
    rows = []
    for (model, gap, meth), grp in per_site.groupby(["model", "gap", "method"], sort=False):
        g2 = grp.set_index(["model", "gap", "cam_id"])
        base = lk.loc[g2.index]
        rows.append({"model": model, "gap": gap, "method": meth, "sites": len(grp), "outages": int(grp.outages.sum()),
                     "hours_scored": int(grp.n.sum()), "median_site_mae": grp.mae.median(),
                     "median_site_mae_moving": grp.mae_moving.median(), "hours_moving": int(grp.n_moving.sum()),
                     "sites_beating_lkv": int((g2.mae < base.mae).sum()),
                     "sites_beating_lkv_moving": int((g2.mae_moving < base.mae_moving).sum()),
                     "within_2sigma": grp.within_2sigma.median() if meth == "fused_bias" else np.nan})
    s = pd.DataFrame(rows)
    s["gap"] = pd.Categorical(s["gap"], list(GAPS), ordered=True)
    s = s.sort_values(["model", "gap", "method"])
    s.round(4).to_csv(OUT / "fusion_summary.csv", index=False)
    print(s.round(3).to_string(index=False))
    (OUT / "fusion.json").write_text(json.dumps({
        "primary": "fused_bias", "camera_models": MODELS, "gaps_h": GAPS, "moving_threshold_ft": MOVING_FT,
        "note": "simulated outages over the calibration history; camera = out-of-fold CV predictions (D-0007 folds)"},
        indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
