"""W2 tidal handling (D-0013 W2-1): detection, the tide-free residual, and no flood alert on an ordinary tide."""
from __future__ import annotations

import numpy as np
import pandas as pd

from riversight.agent import rules, schema, tidal, tools


def tide_series(days=20, surge_at=None, surge_ft=0.0, river=False, seed=0):
    t = pd.date_range("2026-10-01", periods=days * 96, freq="15min", tz="UTC")
    h = (t - t[0]).total_seconds().to_numpy() / 3600
    rng = np.random.default_rng(seed)
    if river:
        y = 5 + 0.02 * h / 24 + 0.05 * np.sin(2 * np.pi * h / 24) + rng.normal(0, 0.02, len(h))
    else:
        y = 28 + 1.6 * np.cos(2 * np.pi * h / 12.4206) + 0.5 * np.cos(2 * np.pi * h / 23.9345) + rng.normal(0, 0.03, len(h))
    s = pd.Series(y, index=t)
    if surge_at is not None:
        s[s.index >= surge_at] += surge_ft
    return s


def test_detects_tide_not_river():
    assert tidal.detect(tide_series())["tidal"] is True
    assert tidal.detect(tide_series(river=True))["tidal"] is False


def test_ordinary_high_tide_is_not_a_rise_but_a_surge_is():
    g = tide_series()
    now = g.index[-1]
    dm = {"daily_max_p90": 30.0, "daily_max_p99": 31.0, "resid_p99": 0.4}
    a = tidal.assess(g[g.index > now - pd.Timedelta("7D")], now, dm)
    assert a["ok"] and not a["non_tidal_rise"] and abs(a["residual_ft"]) < 0.3
    s = tide_series(surge_at=now - pd.Timedelta("3h"), surge_ft=4.5)       # high for the site at any tide phase
    b = tidal.assess(s[s.index > now - pd.Timedelta("7D")], now, {**dm, "daily_max_p90": 29.0})
    assert b["non_tidal_rise"] and b["residual_ft"] > 2.0


def test_rules_never_alert_on_a_tide(monkeypatch):
    """Regression (live, 2026-10-24 18:15Z, First Mallard): an incoming tide was alerted and approved."""
    calls = []

    def fake(ctx, name, args):
        calls.append(name)
        if name == "get_gauge":
            return {"latest_ft": 27.8, "age_min": 0.0, "change_1h_ft": 1.17, "summary": "g",
                    "tidal": {"ok": True, "predicted_tide_ft": 27.8, "residual_ft": 0.0, "surge_threshold_ft": 1.2,
                              "non_tidal_rise": False}}
        return {"summary": name}
    monkeypatch.setattr(tools, "call", fake)
    monkeypatch.setattr(tools, "bundle", lambda ctx, cam: type("B", (), {"meta": {"stage_p50": 26.0, "stage_p90": 28.0}})())
    e = {"event_id": "e", "cam_id": "CA_First_Mallard_Branch_nr_Fairfield", "mode": "eval",
         "reading": {"t_frame": "2026-10-24T18:15:04Z", "frame_key": "k.jpg", "flags": ["RISING"]}, "recent": []}
    d = rules.decide(e, tools.ToolContext(mode="eval"))
    assert schema.action_types(d) == ["NOOP"] and "tide" in d["rationale"] and "render_wet_overlay" not in calls


def test_known_tidal_sites_are_packaged():
    assert tools.site_tidal("CA_First_Mallard_Branch_nr_Fairfield").get("tidal") is True
    assert tools.site_tidal("IL_Salt_Creek_at_Wood_Dale") == {}
