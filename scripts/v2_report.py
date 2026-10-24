"""W4: paired statistics and the seasonal breakdown for the model v2 CV (reads results/v2/cv_*.csv only).

  * paired site bootstrap (10,000 resamples of the 20 sites) of the median-MAE ratio v2 / v1;
  * exact two-sided sign test on per-site MAE (v2 < v1);
  * per calendar month of the test fold: median over sites of the fold MAE, v1 vs v2 (does v2 shrink
    the seasonal drift that dominates year-long CV?);
  * ingredient attribution: each ablation's median MAE relative to v1.

  python scripts/v2_report.py   → results/v2/report.json, results/v2/cv_by_month.csv
"""
from __future__ import annotations

import json
from math import comb
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "results" / "v2"


def main():
    sites = pd.read_csv(V2 / "cv_sites.csv")
    summ = pd.read_csv(V2 / "cv_summary.csv")
    folds = pd.read_csv(V2 / "cv_folds.csv")
    best = summ.loc[summ["selected"], "config"].iloc[0]
    v1 = sites[sites.config == "v1"].set_index("cam_id")["mae"]
    v2 = sites[sites.config == best].set_index("cam_id")["mae"].reindex(v1.index)
    rng = np.random.default_rng(0)
    idx = rng.integers(0, len(v1), (10000, len(v1)))
    ratio = np.median(v2.values[idx], 1) / np.median(v1.values[idx], 1)
    n_better, n = int((v2 < v1).sum()), len(v1)
    k = min(n_better, n - n_better)
    p_sign = min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)
    f = folds[folds.config.isin(["v1", best])].copy()
    f["month"] = f["fold"].str[5:7].astype(int)
    by_month = (f.pivot_table(index=["cam_id", "fold", "month"], columns="config", values="mae").reset_index()
                  .groupby("month").agg(sites=("cam_id", "nunique"), v1_median_mae=("v1", "median"),
                                        v2_median_mae=(best, "median")).reset_index())
    by_month["v2_vs_v1"] = by_month["v2_median_mae"] / by_month["v1_median_mae"] - 1
    by_month.round(4).to_csv(V2 / "cv_by_month.csv", index=False)
    v1m = float(summ.loc[summ.config == "v1", "median_mae"].iloc[0])
    out = {
        "selected_config": best,
        "v1_median_mae_ft": round(v1m, 4),
        "v2_median_mae_ft": round(float(summ.loc[summ.config == best, "median_mae"].iloc[0]), 4),
        "median_mae_ratio_v2_over_v1": round(float(np.median(v2) / np.median(v1)), 4),
        "ratio_bootstrap_95ci": [round(float(np.quantile(ratio, 0.025)), 4), round(float(np.quantile(ratio, 0.975)), 4)],
        "sites_better": n_better, "sites": n, "sign_test_p_two_sided": float(f"{p_sign:.3g}"),
        "worst_site_delta_ft": round(float((v2 - v1).max()), 4), "worst_site": str((v2 - v1).idxmax()),
        "p1_sites_v1": int(summ.loc[summ.config == "v1", "p1_sites"].iloc[0]),
        "p1_sites_v2": int(summ.loc[summ.config == best, "p1_sites"].iloc[0]),
        "d0010_criterion_1": {"bar_ft": round(0.85 * v1m, 4), "met": bool(summ.loc[summ.config == best, "d0010_bar"].iloc[0])},
        "ablation_rel_change": {r.config: round(float(r.rel_change), 4) for r in summ.itertuples()},
        "note": "forward-chaining monthly CV inside the calibration history (D-0007 folds); not the frozen kill-test numbers",
    }
    (V2 / "report.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    print(by_month.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
