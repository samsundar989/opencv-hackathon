"""Fleet-level summary of the frozen kill test v2 (W3).

Reads only committed per-site results (plus the local history segment index, if
present) and writes `results/kill_test_v2_summary.json`. Every headline number in
README/REPORT/judge page must be a value in this file or another committed
results file (`scripts/check_report_numbers.py` checks that).

    python report/summarize_results.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"


def _r(x: float, nd: int = 3) -> float:
    return float(round(float(x), nd))


def summarize(kt: pd.DataFrame, reg: pd.DataFrame, cv: pd.DataFrame,
              fit_cv: pd.DataFrame, gate: pd.DataFrame,
              segments: dict[str, pd.DataFrame] | None = None) -> dict:
    n = len(kt)
    out: dict = {"source": "results/kill_test_v2.csv", "n_sites": n}

    out["p1_sites"] = int(kt["p1"].sum())
    out["p1_sites_mae_only"] = int((kt["mae"] <= 0.25).sum())
    ev = kt[kt["has_events"].astype(bool)]
    out["p2_event_sites"] = int(len(ev))
    out["p2_sites"] = int(ev["p2"].sum())

    out["median_mae_ft"] = _r(kt["mae"].median())
    out["median_nmae"] = _r(kt["nmae"].median())
    out["median_spearman"] = _r(kt["spearman"].median(), 2)
    out["mean_mae_ft"] = _r(kt["mae"].mean())
    out["sites_beat_const"] = int((kt["mae"] < kt["mae_const"]).sum())
    out["sites_beat_persist_24h"] = int((kt["mae"] < kt["mae_p24"]).sum())
    out["sites_beat_persist_15min"] = int((kt["mae"] < kt["mae_p15"]).sum())
    for h in ("6h", "24h", "72h", "7d"):
        out[f"gapfill_sites_beat_lkv_{h}"] = int(
            (kt[f"gap_{h}_cam"] < kt[f"gap_{h}_lkv"]).sum())

    fl = kt[kt["bacc_flood"].notna()]
    out["flood_sites"] = int(len(fl))
    out["flood_bacc_cam_median"] = _r(fl["bacc_flood"].median(), 2)
    out["flood_bacc_persist24_median"] = _r(fl["bacc_flood_p24"].median(), 2)

    out["tiers"] = {t: int(c) for t, c in kt["tier"].value_counts().sort_index().items()}
    out["test_frames_scored"] = int(kt["n"].sum())

    # Registration (SLICE_01, 30-day window, true-daylight frames).
    out["registration"] = {
        "source": "results/kill_test/registration_summary.csv",
        "day_frames": int(reg["day"].sum()),
        "registered": int(reg["registered"].sum()),
        "rate": _r(reg["registered"].sum() / reg["day"].sum()),
        "orb": int(reg["orb"].sum()),
        "orb_rate": _r(reg["orb"].sum() / reg["day"].sum()),
        "aliked_lightglue": int(reg["aliked_lightglue"].sum()),
        "chain": int(reg["chain"].sum()),
    }

    # Year-long forward-chaining CV of the frozen setting (D-0007).
    frozen = json.loads((RES / "scene" / "frozen_config.json").read_text(encoding="utf-8"))
    best = cv[(cv["bs"] == frozen["bs"]) & (cv["thr"] == frozen["thr"])
              & (cv["lam"] == frozen["lam"]) & (cv["smooth"] == frozen["smooth"])].iloc[0]
    out["year_cv"] = {
        "source": "results/scene/tune_cv_summary.csv",
        "p1_sites": int(best["p1_sites"]),
        "median_mae_ft": _r(best["median_mae"]),
        "median_nmae": _r(best["median_nmae"]),
        "settings_tried": int(len(cv)),
    }

    # Classical transect detector vs scene model on the 20-day fit window (D-0006).
    out["fit_window"] = {
        "source": ["results/kill_test/fit_window_cv.csv", "results/scene/gate_fit20.csv"],
        "transect_sites_le_025": int((fit_cv["camera_cv_mae_ft"] <= 0.25).sum()),
        "transect_sites": int(len(fit_cv)),
        "scene_sites_le_025": int((gate["ridgeS_mae"] <= 0.25).sum()),
        "scene_sites": int(len(gate)),
        "scene_median_mae_ft": _r(gate["ridgeS_mae"].median()),
    }

    if segments is not None:
        unlinked = {s: int((~df["linked"].astype(bool)).sum()) for s, df in segments.items()}
        out["history_view_segments"] = {
            "source": "data/derived/<cam>/history/segments.csv (local index)",
            "sites_with_unlinked_segments": int(sum(v > 0 for v in unlinked.values())),
            "per_site_unlinked": {s: v for s, v in sorted(unlinked.items()) if v},
        }
    return out


def main() -> None:
    kt = pd.read_csv(RES / "kill_test_v2.csv")
    reg = pd.read_csv(RES / "kill_test" / "registration_summary.csv")
    cv = pd.read_csv(RES / "scene" / "tune_cv_summary.csv")
    fit_cv = pd.read_csv(RES / "kill_test" / "fit_window_cv.csv")
    gate = pd.read_csv(RES / "scene" / "gate_fit20.csv")
    segs = {}
    for f in sorted((ROOT / "data" / "derived").glob("*/history/segments.csv")):
        segs[f.parents[1].name] = pd.read_csv(f)
    out = summarize(kt, reg, cv, fit_cv, gate, segs or None)
    dst = RES / "kill_test_v2_summary.json"
    dst.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
