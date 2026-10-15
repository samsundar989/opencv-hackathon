"""SLICE_01B step 3 → 4: freeze the tuned global setting (D-0007) before the frozen test days are read.

Takes the top row of results/scene/tune_cv_summary.csv (selection rule in scripts/scene_tune.py, fixed before
tuning ran), adds the pre-registered tier/event rules, writes results/scene/frozen_config.json and records sha256
of that file and of every module the scorer runs in results/constants.sha256.

  python scripts/freeze_config.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CODE = ["scripts/scene_score.py", "scripts/scene_tune.py", "scripts/scene_features.py",
        "src/riversight/eval/protocol_v2.py", "src/riversight/calib/scene_regressor.py",
        "src/riversight/calib/flood_height_map.py", "src/riversight/vision/scene_features.py",
        "src/riversight/vision/register.py", "src/riversight/killtest.py"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    out = ROOT / "results" / "scene" / "frozen_config.json"
    if out.exists():
        sys.exit(f"refusing: {out} already frozen")
    summ = pd.read_csv(ROOT / "results" / "scene" / "tune_cv_summary.csv")
    sites = pd.read_csv(ROOT / "results" / "scene" / "tune_cv_sites.csv")
    best = summ.iloc[0]
    cfg = {
        "decision": "D-0007",
        "bs": int(best["bs"]), "thr": float(best["thr"]), "lam": float(best["lam"]), "smooth": str(best["smooth"]),
        "min_roi": 50,
        "cv": {"sites": int(best["sites"]), "p1_sites_oof": int(best["p1_sites"]),
               "median_nmae_oof": round(float(best["median_nmae"]), 4), "median_mae_oof": round(float(best["median_mae"]), 4),
               "tuned_sites": sorted(sites["cam_id"].unique().tolist())},
        # reporting only (not pass/fail), fixed before scoring:
        "tier_a": ["NY_East_Branch_Delaware_River_at_Hancock_Staff",
                   "WI_East_Branch_Pecatonica_River_near_Blanchardville_Bullet"],
        "tier_c_reg_rate": 0.80, "tier_c_cv_spearman": 0.50, "tier_c_min_days": 90,
        "event_ft": 0.25, "min_event_frames_per_site": 3,
        "calibration_cut_utc": "2026-10-03T00:00:00Z", "test_window_utc": ["2026-10-04T00:00:00Z", "2026-10-14T00:00:00Z"],
        "frozen_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    out.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    lines = [f"{sha(out)}  results/scene/frozen_config.json"] + [f"{sha(ROOT / c)}  {c}" for c in CODE]
    (ROOT / "results" / "constants.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(cfg, indent=2))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
