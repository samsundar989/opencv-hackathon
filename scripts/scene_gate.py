"""SLICE_01B step 1 gate: reproduce Cowork's fit-window numbers (experiments/cowork_2026-10-14) with our
own registration cache and the ported modules. Fit window only — the test days are not loaded.

Protocol "fit20" (as Cowork's model.py / the worker's SLICE_01 CV): first 20 days, 4 contiguous folds of
5 days, predictions smoothed with a causal 3 h median. Models: scene ridge (all blocks), water-block
ridge (flood-height ROI, acc ≥ 0.85, no fallback — as Cowork's control.py), production SceneRegressor
(ROI with all-block fallback below 50 blocks), and the flood-height vote.

  python scripts/scene_gate.py [--hourly]     (--hourly: on-the-hour frames ±10 min, like Cowork)
Writes results/scene/gate_fit20[_hourly].csv and prints the gate comparison.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from riversight.calib.flood_height_map import fit_thr, stage_grid, vote  # noqa: E402
from riversight.calib.scene_regressor import SceneRegressor, causal_median, kernel_ridge  # noqa: E402

REF = ROOT / "experiments" / "cowork_2026-10-14"
SKIP = {"CA_First_Mallard_Branch_nr_Fairfield"}   # tidal; Cowork skipped it too


def load(cam: str, hourly: bool):
    z = np.load(ROOT / "data" / "derived" / cam / "scene_kill30_fit.npz")
    t = pd.to_datetime(z["t"], utc=True)
    h = z["h"]
    keep = np.isfinite(h)
    if hourly:
        keep &= np.abs((t - t.round("h")).total_seconds()) <= 600
    return t[keep], h[keep], z["F"][keep].astype(np.float32)


def fit20(cam: str, hourly: bool) -> dict:
    t, h, X = load(cam, hourly)
    day = (t - t[0]).days
    fold = np.minimum((day * 4) // 20, 3)
    P = {k: np.full(len(h), np.nan) for k in ("ridge", "water", "prod", "vote", "const")}
    nroi = []
    for f in range(4):
        tr, te = fold != f, fold == f
        if te.sum() == 0 or tr.sum() < 30:
            continue
        M = fit_thr(X[tr], h[tr])
        P["ridge"][te] = kernel_ridge(X[tr], h[tr], X[te])
        sel = M.acc >= 0.85
        if sel.sum() >= 20:
            P["water"][te] = kernel_ridge(X[tr][:, sel], h[tr], X[te][:, sel])
        m = SceneRegressor().fit(X[tr], h[tr])
        P["prod"][te] = m.predict(X[te])
        nroi.append(m.n_roi)
        P["vote"][te], _ = vote(M, X[te], stage_grid(h[tr]))
        P["const"][te] = np.median(h[tr])
    r = {"cam_id": cam, "n": len(h), "range_ft": float(h.max() - h.min()), "roi_blocks_median": float(np.median(nroi))}
    for k, p in P.items():
        s = causal_median(t, p, "3h") if k != "const" else p
        ok = np.isfinite(s)
        r[f"{k}S_mae"] = float(np.mean(np.abs(s[ok] - h[ok]))) if ok.any() else np.nan
    return r


def main():
    import yaml
    ap = argparse.ArgumentParser()
    ap.add_argument("--hourly", action="store_true")
    a = ap.parse_args()
    cams = [s["cam_id"] for s in yaml.safe_load((ROOT / "data/sites/kill_test.yaml").read_text(encoding="utf-8"))["sites"]]
    rows = []
    for c in cams:
        if c in SKIP:
            continue
        rows.append(fit20(c, a.hourly))
        print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in rows[-1].items()}, flush=True)
    df = pd.DataFrame(rows)
    out = ROOT / "results" / "scene"
    out.mkdir(parents=True, exist_ok=True)
    df.round(4).to_csv(out / f"gate_fit20{'_hourly' if a.hourly else ''}.csv", index=False)

    # gate: median over the 17 sites both runs share
    ref = pd.read_csv(REF / "results_fit20.csv")
    ctl = pd.read_csv(REF / "control.csv")
    ref["key"] = ref["site"].str[:16]
    ctl["key"] = ctl["site"].str[:16]
    df["key"] = df["cam_id"].str[:16]
    shared = sorted(set(df["key"]) & set(ref["key"]))
    m = df.set_index("key").loc[shared]
    print(f"\nshared sites: {len(shared)}")
    for ours, theirs, col in (("ridgeS_mae", "ridgeS_mae", ref), ("waterS_mae", "water", ctl)):
        a_, b_ = m[ours].median(), col.set_index("key").loc[shared, theirs].median()
        print(f"  {ours:12s} ours {a_:.3f}  cowork {b_:.3f}  diff {a_-b_:+.3f}  {'OK' if abs(a_-b_) <= 0.05 else 'OUTSIDE +-0.05'}")
    for k in ("prodS_mae", "voteS_mae", "constS_mae"):
        print(f"  {k:12s} ours {m[k].median():.3f}")
    print(f"  sites <=0.25 ft (ridge): ours {(m['ridgeS_mae'] <= 0.25).sum()}/{len(shared)}, "
          f"cowork {(ref.set_index('key').loc[shared, 'ridgeS_mae'] <= 0.25).sum()}/{len(shared)}")


if __name__ == "__main__":
    main()
