"""W4: D-0010 §2 decision data. Live v2 shadow vs v1 on the same scored daylight readings.

Reads results/live_prospective/readings.csv (W1's scorer: one row per cycle reading, `abs_err` = frozen v1
live model vs gauge, `shadow_ft` = v2 shadow Kalman estimate) and the v2 CV summary. Paired statistics:
  * pairs, sites, time span; median AE v1 vs v2 on the same rows (criterion 2: v2 no worse than v1);
  * per-site medians; sites where v2 is better; exact sign test over sites;
  * site-cluster bootstrap (10,000) of the difference in pooled median AE (readings are autocorrelated
    within a site, so sites are the resampling unit);
  * stage movement during the period (a calm day is weak evidence for flood behaviour).

  python scripts/v2_shadow_report.py   → results/v2/shadow_decision.json, results/v2/shadow_sites.csv
"""
from __future__ import annotations

import json
from math import comb
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "results" / "live_prospective"
V2 = ROOT / "results" / "v2"


def main():
    r = pd.read_csv(LIVE / "readings.csv", parse_dates=["t_cycle", "t_frame"])
    s = r[r["scored"].astype(bool) & r["shadow_ft"].notna() & r["abs_err"].notna()].copy()
    s["v2_ae"] = (s["shadow_ft"] - s["gauge_ft"]).abs()
    per = (s.groupby("cam_id").agg(n=("v2_ae", "size"), v1_median_ae=("abs_err", "median"), v2_median_ae=("v2_ae", "median"),
                                   gauge_range_ft=("gauge_ft", lambda x: x.max() - x.min())).reset_index())
    per["v2_better"] = per["v2_median_ae"] < per["v1_median_ae"]
    per.round(4).to_csv(V2 / "shadow_sites.csv", index=False)
    n, k = len(per), int(per["v2_better"].sum())
    p_sign = min(1.0, 2 * sum(comb(n, i) for i in range(min(k, n - k) + 1)) / 2 ** n)
    groups = {c: g for c, g in s.groupby("cam_id")}
    cams = list(groups)
    rng = np.random.default_rng(0)
    diffs = []
    for _ in range(10000):
        b = pd.concat([groups[c] for c in rng.choice(cams, len(cams))])
        diffs.append(b["v2_ae"].median() - b["abs_err"].median())
    v1m, v2m = float(s["abs_err"].median()), float(s["v2_ae"].median())
    out = {
        "pairs": int(len(s)), "sites": n, "t_frame_first": str(s["t_frame"].min()), "t_frame_last": str(s["t_frame"].max()),
        "v1_median_ae_ft": round(v1m, 4), "v2_median_ae_ft": round(v2m, 4),
        "diff_v2_minus_v1_ft": round(v2m - v1m, 4),
        "diff_site_bootstrap_95ci": [round(float(np.quantile(diffs, 0.025)), 4), round(float(np.quantile(diffs, 0.975)), 4)],
        "sites_v2_better": k, "sign_test_p_two_sided": float(f"{p_sign:.3g}"),
        "median_gauge_range_ft_per_site": round(float(per["gauge_range_ft"].median()), 3),
        "max_gauge_range_ft_per_site": round(float(per["gauge_range_ft"].max()), 3),
        "criterion_2_v2_no_worse": bool(v2m <= v1m),
        "criterion_1_cv": json.loads((V2 / "report.json").read_text(encoding="utf-8"))["d0010_criterion_1"],
        "d0012_min_pairs_40": bool(len(s) >= 40),
        "note": "v1 = frozen first-deployed live bundles (D-0010 §1); v2 = shadow bundles models/sites_v2 "
                "(committed 2026-10-24 04:36Z in 4521e4c, before every scored frame). Criterion 3 (cycle time) is W1's measurement.",
    }
    (V2 / "shadow_decision.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    print(per.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
