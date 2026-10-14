"""SLICE_01 dev evidence: fit-window camera CV vs trivial baselines (constant median, persistence-24h),
on the same registered daytime fit-window frames. Never reads test-window rows.

  python scripts/fit_window_baselines.py --cv-dir <results/kill_test dir of a --dev run>
Writes results/kill_test/fit_window_cv.csv.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cv-dir", type=Path, default=ROOT / "results/kill_test")
    a = ap.parse_args()
    doc = yaml.safe_load((ROOT / "data/sites/kill_test.yaml").read_text(encoding="utf-8"))
    rows = []
    for s in doc["sites"]:
        cam = s["cam_id"]; d = ROOT / "data/derived" / cam
        D = pd.read_parquet(d / "detections.parquet")
        F = D[D["window"] == "fit"].drop_duplicates("idx")
        g = F.set_index("idx")["stage_ft"].dropna()
        st = pd.read_parquet(d / "stage.parquet")[["time", "value"]].sort_values("time")
        q = pd.DataFrame({"t": F["time"] - pd.Timedelta(hours=24), "i": F["idx"]}).sort_values("t")
        p = pd.merge_asof(q, st, left_on="t", right_on="time", direction="backward",
                          tolerance=pd.Timedelta(hours=1)).set_index("i")["value"].reindex(g.index)
        cvf = a.cv_dir / cam / "cv_selection.csv"
        cam_mae = cov = np.nan; det = ""
        if cvf.exists() and cvf.stat().st_size > 5:
            cv = pd.read_csv(cvf); fu = cv[cv["transect"] == "FUSED"].sort_values("cv_mae_ft")
            if len(fu):
                cam_mae, cov, det = float(fu["cv_mae_ft"].iloc[0]), float(fu["cv_coverage"].iloc[0]), fu["detector"].iloc[0]
        rows.append({"site": cam, "fit_frames": len(g), "fit_p05": g.quantile(.05), "fit_p95": g.quantile(.95),
                     "fit_max": g.max(), "camera_cv_mae_ft": cam_mae, "camera_cv_coverage": cov, "detector": det,
                     "const_median_mae_ft": float((g - g.median()).abs().mean()),
                     "persist24_mae_ft": float((g - p).abs().mean()),
                     })
    S = pd.DataFrame(rows)
    S["beats_const"] = S["camera_cv_mae_ft"] < S["const_median_mae_ft"]
    S["beats_persist24"] = S["camera_cv_mae_ft"] < S["persist24_mae_ft"]
    out = ROOT / "results/kill_test/fit_window_cv.csv"; S.round(4).to_csv(out, index=False)
    print(S.round(3).to_string(index=False))
    print("beats const:", int(S["beats_const"].sum()), " beats persist24:", int(S["beats_persist24"].sum()),
          " camera CV MAE<=0.25:", int((S["camera_cv_mae_ft"] <= 0.25).sum()))


if __name__ == "__main__":
    main()
