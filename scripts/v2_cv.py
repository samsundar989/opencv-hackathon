"""W4 step 4: model v2 ablations under exactly the D-0007 forward-chaining monthly CV (D-0010 §2).

Same data, folds and fixed knobs as scripts/scene_tune.py: calibration frames with t < 2026-10-03 00Z
(history ∪ SLICE_01 fit window, deduplicated by filename), monthly folds with a 7-day gap (≥150 training
frames over ≥30 days, ≥20 test frames), block size 4, reliability ≥ 0.80 (≥50 ROI blocks else all), λ = 1,
causal Kalman with q from the training gauge and r from the LOO residuals. The frozen kill-test numbers are
not touched; nothing here opens the frozen test days.

Configurations (ablation table; `v1` must reproduce results/scene/tune_cv_sites.csv at the D-0007 setting):
  v1                 D-0007 frozen setting
  dino_roi           DINO patches only, DINO-space reliability ROI (fit_thr on tokens, ≥0.80; ≥10 patches)
  dino_v1roi         DINO patches only, patches under the v1 ROI blocks
  dino_all           DINO patches only, all 448 patches
  v1+dino_roi@w      K = (1−w)K_v1 + w K_dino_roi, w ∈ {0.3, 0.5}
  v1+dino_v1roi@0.5
  v1+gmean@0.3       mean patch token (global scene descriptor)
  …+norm             (b) per-frame scene-mean removal of DINO tokens
  …+sun / +sundoy    (a) LOO-residual nuisance regression on sun elevation/azimuth (+ day of year)
  …+rec45 / +rec120  (c) recency weighting τ = 45 / 120 days

Selection rule (fixed here, in this commit, before any v2 CV result exists):
  best v2 = the non-v1 configuration with the lowest median (over sites) pooled out-of-fold MAE among those
  with no site worse than v1 by > 0.10 ft; ties → more P1 sites → lower median nMAE. If none qualifies, the
  best is the lowest median MAE and the report says it fails the per-site guard.
  D-0010 §2 bar for serving: median MAE ≤ 0.85 × v1 (0.380 → ≤ 0.323 ft) and no site worse by > 0.10 ft.

  scripts/v2_cv.py --jobs 5            per-site OOF cached in data/derived/<cam>/v2_cv.npz
  scripts/v2_cv.py --summarise         → results/v2/cv_sites.csv, cv_summary.csv, cv_folds.csv
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
THR, LAM, MIN_ROI, MIN_DINO_ROI = 0.80, 1.0, 50, 10
OUT = ROOT / "results" / "v2"

BASE = "v1+dino_roi@0.5"
CONFIGS = ["v1", "dino_roi", "dino_v1roi", "dino_all", "dino_roi+norm",
           "v1+dino_roi@0.3", "v1+dino_roi@0.5", "v1+dino_v1roi@0.5", "v1+gmean@0.3", "v1+dino_roi+norm@0.5",
           "v1+sun", "v1+sundoy", "v1+rec45", "v1+rec120",
           BASE + "+sun", BASE + "+sundoy", BASE + "+rec45", BASE + "+rec120",
           "v1+dino_roi+norm@0.5+sun+rec120"]


def parse(cfg: str) -> dict:
    """'v1+dino_roi+norm@0.5+sun+rec120' → kernels, weight, ingredients."""
    parts = cfg.split("+")
    d = {"v1": "v1" in parts, "dino": None, "w": 1.0, "norm": False, "sun": None, "tau": None}
    for p in parts:
        name, _, w = p.partition("@")
        if name.startswith("dino_") or name == "gmean":
            d["dino"] = name
        if name == "norm":
            d["norm"] = True
        if name in ("sun", "sundoy"):
            d["sun"] = name
        if name.startswith("rec"):
            d["tau"] = float(name[3:])
        if w:
            d["w"] = float(w)
    if not d["v1"]:
        d["w"] = 1.0
    elif d["dino"] is None:
        d["w"] = 0.0
    return d


def load_site(cam: str):
    """(t, h, F v1 float16, P dino float16, gmean float16) aligned by filename, time-sorted, t < CUT."""
    from scene_tune import CUT
    metas, feats = [], []
    for name in ("scene_history_all.npz", "scene_kill30_fit.npz"):
        p = DATA / "derived" / cam / name
        if p.exists():
            z = np.load(p)
            metas.append(pd.DataFrame({"t": z["t"], "h": z["h"], "fn": z["filename"], "src": len(feats),
                                       "k": np.arange(len(z["t"]))}))
            feats.append(z["F"])
    df = pd.concat(metas, ignore_index=True)
    df["t"] = pd.to_datetime(df["t"], utc=True)
    df = df[(df["t"] < CUT) & np.isfinite(df["h"])].drop_duplicates("fn").sort_values("t").reset_index(drop=True)
    zd = np.load(DATA / "derived" / cam / "dino_calib.npz")
    pos = {f: i for i, f in enumerate(zd["filename"])}
    df = df[df["fn"].isin(pos)].reset_index(drop=True)
    F = np.stack([feats[s][k] for s, k in zip(df["src"], df["k"])])
    j = np.array([pos[f] for f in df["fn"]])
    return pd.DatetimeIndex(df["t"]), df["h"].to_numpy(float), F, zd["P"][j], zd["gmean"][j], df["fn"].to_numpy(str)


def run_site(cam: str) -> str:
    from riversight.calib import scene_v2 as S
    from riversight.calib.flood_height_map import fit_thr
    from riversight.calib.scene_regressor import kalman_1d, kalman_params
    from riversight.killtest import site_latlng
    from riversight.vision.dino_features import patch_of_block
    from scene_tune import gauge_series, month_folds
    out = DATA / "derived" / cam / "v2_cv.npz"
    if out.exists():
        return f"{cam}: cached"
    t0 = time.time()
    t, h, F16, P16, G16, fn = load_site(cam)
    folds = month_folds(t)
    g = gauge_series(cam)
    lat, lng = site_latlng(DATA, cam)
    Zs, Zd = S.nuisance_matrix(t, lat, lng, False), S.nuisance_matrix(t, lat, lng, True)
    X = F16.astype(np.float32)
    Pn = S.scene_mean_removed(P16.astype(np.float32))
    Pr = P16.astype(np.float32)
    Gm = G16.astype(np.float32)
    pob = patch_of_block()
    specs = {c: parse(c) for c in CONFIGS}
    pred = {c: np.full(len(h), np.nan) for c in CONFIGS}
    raw = {c: np.full(len(h), np.nan) for c in CONFIGS}
    info = []
    fold_id = np.full(len(h), "", dtype=object)
    for name, tr, te in folds:
        fold_id[te] = name
        ntr, nte = int(tr.sum()), int(te.sum())
        M = fit_thr(X[tr], h[tr])
        roi = M.acc >= THR
        if roi.sum() < MIN_ROI:
            roi = np.ones_like(roi)
        q, _ = kalman_params(g[g.index < t[tr][-1]].index, g[g.index < t[tr][-1]].values, np.zeros(4))
        K = {"v1": S.linear_kernel(X[tr][:, roi].reshape(ntr, -1), X[te][:, roi].reshape(nte, -1))}
        droi = {}
        for norm, PP in ((False, Pr), (True, Pn)):
            Md = fit_thr(PP[tr], h[tr])
            sel = Md.acc >= THR
            if sel.sum() < MIN_DINO_ROI:
                sel = np.ones_like(sel)
            droi[norm] = sel
            K[("dino_roi", norm)] = S.linear_kernel(PP[tr][:, sel].reshape(ntr, -1), PP[te][:, sel].reshape(nte, -1))
        v1p = np.zeros(Pr.shape[1], bool)
        v1p[np.unique(pob[roi])] = True
        K[("dino_v1roi", False)] = S.linear_kernel(Pr[tr][:, v1p].reshape(ntr, -1), Pr[te][:, v1p].reshape(nte, -1))
        K[("dino_all", False)] = S.linear_kernel(Pr[tr].reshape(ntr, -1), Pr[te].reshape(nte, -1))
        K[("gmean", False)] = S.linear_kernel(Gm[tr], Gm[te])
        info.append({"fold": name, "n_tr": ntr, "n_te": nte, "roi_v1": int(roi.sum()), "roi_dino": int(droi[False].sum()),
                     "roi_dino_norm": int(droi[True].sum()), "v1roi_patches": int(v1p.sum())})
        for c, s in specs.items():
            Ktr, Kte = 0.0, 0.0
            if s["v1"]:
                Ktr, Kte = Ktr + (1 - s["w"]) * K["v1"][0], Kte + (1 - s["w"]) * K["v1"][1]
            if s["dino"]:
                kd = K[(s["dino"], s["norm"])]
                Ktr, Kte = Ktr + s["w"] * kd[0], Kte + s["w"] * kd[1]
            sw = S.recency_weights(t[tr], s["tau"]) if s["tau"] else None
            p, loo = S.ridge_dual(Ktr, Kte, h[tr], LAM, sw)
            if s["sun"]:
                Z = Zs if s["sun"] == "sun" else Zd
                bias_te = S.nuisance_fit(Z[tr], loo, Z[te])
                loo = loo - S.nuisance_fit(Z[tr], loo, Z[tr])
                p = p + bias_te
            raw[c][te] = p
            pred[c][te] = kalman_1d(t[te], p, q, S.kalman_r(loo))[0]
    np.savez_compressed(out, t=t.asi8, h=h, fold=fold_id.astype(str), configs=np.array(CONFIGS),
                        P=np.stack([pred[c] for c in CONFIGS]), R=np.stack([raw[c] for c in CONFIGS]),
                        p5=np.quantile(h, 0.05), p95=np.quantile(h, 0.95), span_days=(t[-1] - t[0]).days,
                        folds=np.array(pd.DataFrame(info).to_json(orient="records")))
    return f"{cam}: {len(t)} frames, {len(folds)} folds ({time.time() - t0:.0f}s)"


def summarise(cams: list[str]):
    rows, frows = [], []
    for cam in cams:
        p = DATA / "derived" / cam / "v2_cv.npz"
        if not p.exists():
            continue
        z = np.load(p)
        h, rng = z["h"], max(float(z["p95"] - z["p5"]), 1e-6)
        for c, pr in zip(z["configs"], z["P"]):
            ok = np.isfinite(pr)
            mae = float(np.mean(np.abs(pr[ok] - h[ok])))
            rows.append({"cam_id": cam, "config": c, "n_oof": int(ok.sum()), "n_folds": len(set(z["fold"][ok])),
                         "span_days": int(z["span_days"]), "mae": mae, "median_ae": float(np.median(np.abs(pr[ok] - h[ok]))),
                         "nmae": mae / rng, "p1": (mae <= 0.25) or (mae / rng <= 0.10)})
            for f in sorted(set(z["fold"][ok])):
                m = ok & (z["fold"] == f)
                frows.append({"cam_id": cam, "config": c, "fold": f, "n": int(m.sum()),
                              "mae": float(np.mean(np.abs(pr[m] - h[m])))})
    df = pd.DataFrame(rows)
    if df.empty:
        print("no sites yet")
        return
    v1 = df[df.config == "v1"].set_index("cam_id")["mae"]
    df["d_vs_v1"] = df["mae"] - df["cam_id"].map(v1)
    agg = (df.groupby("config", sort=False)
             .agg(sites=("cam_id", "nunique"), median_mae=("mae", "median"), mean_mae=("mae", "mean"),
                  median_nmae=("nmae", "median"), p1_sites=("p1", "sum"),
                  sites_better=("d_vs_v1", lambda d: int((d < 0).sum())),
                  worst_site_delta=("d_vs_v1", "max"))
             .reset_index())
    v1m = float(agg.loc[agg.config == "v1", "median_mae"].iloc[0])
    agg["rel_change"] = agg["median_mae"] / v1m - 1
    agg["guard_ok"] = agg["worst_site_delta"] <= 0.10
    agg["d0010_bar"] = agg["guard_ok"] & (agg["median_mae"] <= 0.85 * v1m)
    cand = agg[agg.config != "v1"].copy()
    pool = cand[cand.guard_ok] if cand.guard_ok.any() else cand
    best = pool.sort_values(["median_mae", "p1_sites", "median_nmae"], ascending=[True, False, True]).iloc[0]
    agg["selected"] = agg.config == best.config
    OUT.mkdir(parents=True, exist_ok=True)
    df.round(4).to_csv(OUT / "cv_sites.csv", index=False)
    agg.round(4).to_csv(OUT / "cv_summary.csv", index=False)
    pd.DataFrame(frows).round(4).to_csv(OUT / "cv_folds.csv", index=False)
    print(agg.round(4).to_string(index=False))
    print(f"\nselected (pre-registered rule): {best.config}  median MAE {best.median_mae:.3f} ft vs v1 {v1m:.3f} "
          f"({best.median_mae / v1m - 1:+.1%}); worst site {best.worst_site_delta:+.3f} ft; "
          f"D-0010 bar {'MET' if bool(agg.loc[agg.selected, 'd0010_bar'].iloc[0]) else 'NOT met'}")


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
    n = 0
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(run_site, c): c for c in cams}
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
