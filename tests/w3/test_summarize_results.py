import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("summarize_results", ROOT / "report" / "summarize_results.py")
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)


def _load():
    res = ROOT / "results"
    return (pd.read_csv(res / "kill_test_v2.csv"),
            pd.read_csv(res / "kill_test" / "registration_summary.csv"),
            pd.read_csv(res / "scene" / "tune_cv_summary.csv"),
            pd.read_csv(res / "kill_test" / "fit_window_cv.csv"),
            pd.read_csv(res / "scene" / "gate_fit20.csv"))


def test_summary_matches_frozen_verdict():
    import json
    out = sr.summarize(*_load())
    verdict = json.loads((ROOT / "results" / "kill_test_v2_verdict.json").read_text())
    assert out["p1_sites"] == verdict["P1_sites"]
    assert out["p2_sites"] == verdict["P2_sites"]
    assert out["p2_event_sites"] == verdict["P2_event_sites"]
    assert abs(out["registration"]["rate"] - verdict["reg_rate"]) < 1e-3
    assert out["year_cv"]["median_mae_ft"] == verdict["config"]["cv"]["median_mae_oof"]


def test_summary_without_segments_omits_view_block():
    out = sr.summarize(*_load(), segments=None)
    assert "history_view_segments" not in out


def test_committed_summary_is_current():
    import json
    committed = json.loads((ROOT / "results" / "kill_test_v2_summary.json").read_text())
    fresh = sr.summarize(*_load())
    for k, v in fresh.items():
        assert committed[k] == v, k
