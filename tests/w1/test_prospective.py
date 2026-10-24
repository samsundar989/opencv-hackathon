"""W1: prospective scoring rules (D-0010 §1) on synthetic readings."""
import numpy as np
import pandas as pd

from riversight.live import prospective as pv


def test_scoring_rules():
    t0 = pd.Timestamp("2026-10-24T15:00:00Z")
    frozen = {"models": {"A": {"model_sha": "abc123def4567890", "nwis_id": "1"}}}
    g = pd.Series([5.0, 5.1, 5.2], index=pd.DatetimeIndex([t0 - pd.Timedelta("24h"), t0 - pd.Timedelta("10min"), t0 + pd.Timedelta("2h")]))
    rows = [  # scored, saturated, wrong model, night, no gauge within 20 min
        {"cam_id": "A", "t_frame": t0, "t_cycle": t0, "daylight": True, "reg_ok": True, "model_sha": "abc123def456",
         "camera_ft": 5.3, "camera_at_least_ft": None, "flags": "", "status": "ok", "agent_actions": ""},
        {"cam_id": "A", "t_frame": t0 + pd.Timedelta("1min"), "t_cycle": t0, "daylight": True, "reg_ok": True,
         "model_sha": "abc123def456", "camera_ft": None, "camera_at_least_ft": 6.0, "flags": "OUT_OF_RANGE",
         "status": "above_range", "agent_actions": "OPEN_TICKET"},
        {"cam_id": "A", "t_frame": t0 + pd.Timedelta("2min"), "t_cycle": t0, "daylight": True, "reg_ok": True,
         "model_sha": "v2v2v2v2v2v2", "camera_ft": 9.0, "camera_at_least_ft": None, "flags": "", "status": "ok", "agent_actions": ""},
        {"cam_id": "A", "t_frame": t0 + pd.Timedelta("3min"), "t_cycle": t0, "daylight": False, "reg_ok": False,
         "model_sha": "abc123def456", "camera_ft": None, "camera_at_least_ft": None, "flags": "NIGHT", "status": "night", "agent_actions": ""},
        {"cam_id": "A", "t_frame": t0 + pd.Timedelta("60min"), "t_cycle": t0, "daylight": True, "reg_ok": True,
         "model_sha": "abc123def456", "camera_ft": 5.0, "camera_at_least_ft": None, "flags": "", "status": "ok", "agent_actions": ""},
    ]
    df, per_site, summary = pv.score(pd.DataFrame(rows), frozen, {"1": g}, {"A": "1"})
    assert df["scored"].tolist() == [True, False, False, False, False]
    assert np.isclose(df.loc[0, "abs_err"], 0.2) and np.isclose(df.loc[0, "lkv24_abs_err"], 0.1)
    assert summary["fleet"]["saturated_gauge_trusted"] == 1 and summary["fleet"]["scored"] == 1
    assert summary["fleet"]["agent_actions"] == {"OPEN_TICKET": 1}
