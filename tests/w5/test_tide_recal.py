"""D-0015 (W5 takes W2's D-0014 items): king-tide TIDE_ADVISORY and RECALIBRATE as rules actions."""
import numpy as np
import pandas as pd

from riversight.agent import once_per, rules, schema, tidal, tools
from riversight.agent.store import Sink


def _tide(days=20, start="2026-01-01"):
    t = pd.date_range(start, periods=days * 24 * 4, freq="15min", tz="UTC")
    h = (t - t[0]).total_seconds().to_numpy() / 3600
    v = 10 + 2.0 * np.cos(2 * np.pi * h / 12.4206) + 0.8 * np.cos(2 * np.pi * h / 12.0)   # spring when in phase
    return pd.Series(v, index=t)


def test_forecast_resolves_spring_neap_and_flags_king_tide():
    g = _tide()
    now = g.index[-1]
    fc = tidal.forecast_high(g, now)
    assert fc is not None and fc["fit_days_used"] >= 14
    # the true next-24 h maximum of the generating signal
    ts = pd.date_range(now, now + pd.Timedelta(hours=24), freq="10min")
    h = (ts - g.index[0]).total_seconds().to_numpy() / 3600
    truth = (10 + 2.0 * np.cos(2 * np.pi * h / 12.4206) + 0.8 * np.cos(2 * np.pi * h / 12.0)).max()
    assert abs(fc["predicted_high_ft"] - truth) < 0.05
    assert tidal.king_tide(fc, {"daily_max_p99": truth - 0.1})
    assert not tidal.king_tide(fc, {"daily_max_p99": truth + 0.5})
    assert not tidal.king_tide(None, {"daily_max_p99": 1.0})


def _ctx(flags, **kw):
    ev = {"cam_id": "C", "event_id": "e", "mode": "eval",
          "reading": {"cam_id": "C", "flags": flags, "frame_key": "f", "model_sha": "served", "t_frame": "2026-01-01T00:00:00Z"}}
    return ev, tools.ToolContext(mode="eval", event=ev, now=pd.Timestamp("2026-01-01", tz="UTC"), **kw)


def test_rising_on_tidal_site(monkeypatch):
    tide = {"ok": True, "non_tidal_rise": False, "predicted_tide_ft": 9.0, "residual_ft": 0.1, "surge_threshold_ft": 0.5,
            "daily_max_p99_ft": 12.5, "predicted_high_24h_ft": 12.7, "predicted_high_time": "2026-01-01T06:00:00+00:00"}
    calls = {"get_gauge": {"latest_ft": 9.1, "age_min": 5, "change_1h_ft": 0.4, "tidal": dict(tide, king_tide=True)}}
    monkeypatch.setattr(tools, "call", lambda ctx, name, args: calls.get(name, {}))
    monkeypatch.setattr(rules, "_meta", lambda ctx, cam: {})
    ev, ctx = _ctx(["RISING"])
    d = rules.decide(ev, ctx)
    assert schema.action_types(d) == ["TIDE_ADVISORY"]
    a = d["actions"][0]
    assert a["needs_approval"] and a["args"]["severity"] == "low" and d["approval_id"]
    calls["get_gauge"]["tidal"] = dict(tide, king_tide=False)
    d = rules.decide(ev, ctx)
    assert schema.action_types(d) == ["NOOP"] and d["approval_id"] is None


def test_recal_status_and_rule(monkeypatch):
    drift = {"n": 40, "sigma_ft": 0.2, "median_residual_ft": 0.45, "median_abs_residual_ft": 0.5, "drifting": True}
    meta = {"model_sha": "refit", "parent_model_sha": "served", "n_new_frames": 120, "stage_max_before_ft": 5.0,
            "stage_max_after_ft": 5.0, "new_from": "2026-01-01", "new_to": "2026-01-07"}
    _, ctx = _ctx(["DISAGREE"], recal_inline={"drift": drift, "recal_meta": meta})
    rs = tools.recal_status(ctx, "C")
    assert rs["available"] and rs["drifting"] and not rs["range_extended"]
    # a refit built on another model, or the served model itself, is not usable
    _, c2 = _ctx(["DISAGREE"], recal_inline={"drift": drift, "recal_meta": dict(meta, parent_model_sha="older")})
    assert not tools.recal_status(c2, "C")["available"]
    _, c3 = _ctx(["DISAGREE"], recal_inline={"drift": drift, "recal_meta": dict(meta, model_sha="served")})
    assert not tools.recal_status(c3, "C")["available"]
    # range extension alone (a flood) also qualifies
    _, c4 = _ctx(["OUT_OF_RANGE"], recal_inline={"drift": dict(drift, drifting=False),
                                                 "recal_meta": dict(meta, stage_max_after_ft=6.2)})
    assert tools.recal_status(c4, "C")["range_extended"]

    ev, ctx = _ctx(["DISAGREE"], recal_inline={"drift": drift, "recal_meta": meta})
    real = tools.call
    monkeypatch.setattr(rules, "BEHAVIOURS", {})                     # isolate the recalibration step
    monkeypatch.setattr(tools, "call", lambda c, name, args: real(c, name, args) if name == "recal_status" else {})
    d = rules.decide(ev, ctx)
    assert schema.action_types(d) == ["RECALIBRATE"] and d["actions"][0]["needs_approval"]
    assert d["actions"][0]["args"]["recal_model_sha"] == "refit" and d["actions"][0]["args"]["reason"] == "drifting"
    # not drifting and range unchanged -> nothing; a moved camera -> nothing
    ev2, ctx2 = _ctx(["DISAGREE"], recal_inline={"drift": dict(drift, drifting=False), "recal_meta": meta})
    assert schema.action_types(rules.decide(ev2, ctx2)) == ["NOOP"]
    ev3, ctx3 = _ctx(["DISAGREE", "VIEW_CHANGE"], recal_inline={"drift": drift, "recal_meta": meta})
    assert "RECALIBRATE" not in schema.action_types(rules.decide(ev3, ctx3))


def test_once_per_suppresses_repeats(tmp_path):
    sink = Sink(local_dir=tmp_path, bucket="")
    ev = {"cam_id": "C", "event_id": "e1", "reading": {"t_frame": "2026-01-01T00:00:00Z"}}

    def dec():
        d = schema.new_decision(ev, "rules")
        d["actions"] = [schema.action("TIDE_ADVISORY", severity="low")]
        return schema.finalize(ev, d)
    assert schema.action_types(once_per(ev, dec(), sink, "TIDE_ADVISORY", 12)) == ["TIDE_ADVISORY"]
    ev["reading"]["t_frame"] = "2026-01-01T06:00:00Z"
    d = once_per(ev, dec(), sink, "TIDE_ADVISORY", 12)
    assert schema.action_types(d) == ["NOOP"] and d["approval_id"] is None
    ev["reading"]["t_frame"] = "2026-01-01T13:00:00Z"
    assert schema.action_types(once_per(ev, dec(), sink, "TIDE_ADVISORY", 12)) == ["TIDE_ADVISORY"]
