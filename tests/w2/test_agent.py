"""W2 River Steward: policy behaviours on canned tool outputs, the LLM loop on a fake Bedrock, guard rails."""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from riversight import agent
from riversight.agent import faults, llm, rules, schema, tools
from riversight.agent.store import Sink

ROOT = Path(__file__).resolve().parents[2]


def ev(flags, recent_flags=(), mode="eval", **reading):
    r = {"t_frame": "2026-10-05T15:00:00Z", "frame_key": "k.jpg", "flags": list(flags), "gauge_stage_ft": 5.0, **reading}
    return {"event_id": "e1", "cam_id": "CAM", "mode": mode, "reading": r,
            "recent": [{"flags": list(f), "frame_key": "old.jpg", "registration": {"ok": True}} for f in recent_flags],
            "site_meta": {"stage_p50": 4.0, "stage_p90": 6.0}}


def canned(monkeypatch, **out):
    """Replace tools.call with canned results per tool name; record calls."""
    calls = []

    def fake(ctx, name, args):
        calls.append(name)
        res = out.get(name, {})
        return {"summary": name, **(res(args) if callable(res) else res)}
    monkeypatch.setattr(tools, "call", fake)
    monkeypatch.setattr(tools, "bundle", lambda ctx, cam: type("B", (), {"meta": {"stage_p50": 4.0, "stage_p90": 6.0}})())
    return calls


CTX = lambda: tools.ToolContext(mode="eval", sink=None)          # noqa: E731
GOOD_Q = {"usable": True, "issues": []}


def acts(d):
    return set(schema.action_types(d))


# ---- VIEW_CHANGE ----

def test_view_change_transient_fog_is_noop(monkeypatch):
    canned(monkeypatch, image_quality={"usable": False, "issues": ["fog"]})
    assert acts(rules.decide(ev(["VIEW_CHANGE"]), CTX())) == {"NOOP"}


def test_view_change_banked_calibrated_reference_reanchors(monkeypatch):
    canned(monkeypatch, image_quality=GOOD_Q,
           reregister_fullres={"best": {"ok": True, "ref": "reference_20251214.jpg", "calibrated": True, "inliers": 80}})
    d = rules.decide(ev(["VIEW_CHANGE"]), CTX())
    assert acts(d) == {"SET_REFERENCE"} and d["actions"][0]["args"]["ref"] == "reference_20251214.jpg"
    assert d["approval_id"] is None


def test_view_change_registers_to_current_is_noop(monkeypatch):
    canned(monkeypatch, image_quality=GOOD_Q, reregister_fullres={"best": {"ok": True, "ref": "reference.jpg", "calibrated": True}})
    assert acts(rules.decide(ev(["VIEW_CHANGE"]), CTX())) == {"NOOP"}


def test_view_change_new_view_quarantines_then_tickets_when_persistent(monkeypatch):
    canned(monkeypatch, image_quality=GOOD_Q, reregister_fullres={"best": {"ok": False, "inliers": 4}})
    assert acts(rules.decide(ev(["VIEW_CHANGE"]), CTX())) == {"QUARANTINE"}
    d = rules.decide(ev(["VIEW_CHANGE"], recent_flags=[["VIEW_CHANGE"], ["VIEW_CHANGE"]]), CTX())
    assert acts(d) == {"QUARANTINE", "OPEN_TICKET"} and d["approval_id"].startswith("apr-")


# ---- GAUGE_STALE ----

def test_gauge_stale_camera_gapfill(monkeypatch):
    canned(monkeypatch, image_quality=GOOD_Q,
           estimate_stage={"ok": True, "stage_ft": 5.4, "sigma_ft": 0.3, "in_calibrated_range": True})
    d = rules.decide(ev(["GAUGE_STALE"]), CTX())
    assert acts(d) == {"MARK_PROVISIONAL", "DENSIFY"}
    assert d["actions"][0]["args"] == {"source": "camera", "stage_ft": 5.4, "sigma_ft": 0.3}


def test_gauge_stale_untrustworthy_camera_holds_last_known(monkeypatch):
    canned(monkeypatch, image_quality={"usable": False, "issues": ["ir_or_night"]},
           estimate_stage={"ok": True, "stage_ft": 5.4, "sigma_ft": 0.3, "in_calibrated_range": True})
    d = rules.decide(ev(["GAUGE_STALE"]), CTX())
    assert acts(d) == {"MARK_PROVISIONAL"} and d["actions"][0]["args"]["source"] == "last_known"


# ---- DISAGREE ----

def test_disagree_camera_fault_quarantines(monkeypatch):
    canned(monkeypatch, image_quality={"usable": False, "issues": ["texture_loss"]}, estimate_stage={"ok": True, "stage_ft": 3.0})
    assert acts(rules.decide(ev(["DISAGREE"]), CTX())) == {"QUARANTINE"}


def test_disagree_isolated_gauge_jump_is_gauge_suspect_ticket(monkeypatch):
    canned(monkeypatch, image_quality=GOOD_Q, estimate_stage={"ok": True, "stage_ft": 5.0, "sigma_ft": 0.2},
           get_gauge={"latest_ft": 5.8, "max_step_ft": 0.8, "step_isolation": 20, "flat_hours": 0})
    d = rules.decide(ev(["DISAGREE"]), CTX())
    assert acts(d) == {"OPEN_TICKET"} and d["actions"][0]["needs_approval"]


def test_disagree_resolved_on_fresh_estimate_is_noop(monkeypatch):
    canned(monkeypatch, image_quality=GOOD_Q, estimate_stage={"ok": True, "stage_ft": 5.1, "sigma_ft": 0.2},
           get_gauge={"latest_ft": 5.0, "max_step_ft": 0.02, "step_isolation": 1, "flat_hours": 0})
    assert acts(rules.decide(ev(["DISAGREE"]), CTX())) == {"NOOP"}


# ---- RISING ----

def test_rising_high_stage_drafts_alert_with_overlays(monkeypatch):
    canned(monkeypatch, get_gauge={"latest_ft": 6.5, "age_min": 15, "change_1h_ft": 0.4},
           get_nws_forecast={"available": False}, render_wet_overlay=lambda a: {"overlay_key": f"ov_{a['stage_ft']}"})
    d = rules.decide(ev(["RISING"]), CTX())
    assert acts(d) == {"DENSIFY", "DRAFT_ALERT"}
    alert = next(a for a in d["actions"] if a["type"] == "DRAFT_ALERT")
    assert alert["needs_approval"] and alert["args"]["overlay_now"] == "ov_6.5" and alert["args"]["crest_ft"] == 7.7


def test_rising_uses_gauge_reading_zero_minutes_old(monkeypatch):
    """Regression (Hancock replay): age_min 0.0 is a fresh gauge; it was treated as missing and the saturated
    camera (10.2 ft) replaced the 17.1 ft gauge, so no alert was drafted."""
    canned(monkeypatch, get_gauge={"latest_ft": 17.1, "age_min": 0.0, "change_1h_ft": -0.3},
           estimate_stage={"ok": True, "stage_ft": 4.0}, get_nws_forecast={"available": False},
           render_wet_overlay={"overlay_key": "ov"})
    d = rules.decide(ev(["RISING"]), CTX())
    assert "DRAFT_ALERT" in acts(d) and next(a for a in d["actions"] if a["type"] == "DRAFT_ALERT")["args"]["stage_ft"] == 17.1


def test_rising_low_stage_only_densifies(monkeypatch):
    canned(monkeypatch, get_gauge={"latest_ft": 4.2, "age_min": 15, "change_1h_ft": 0.1}, get_nws_forecast={"available": False})
    assert acts(rules.decide(ev(["RISING"]), CTX())) == {"DENSIFY"}


# ---- OUT_OF_RANGE and muddy water (D-0009) ----

def canned_range(monkeypatch, **out):
    calls = canned(monkeypatch, **out)
    monkeypatch.setattr(tools, "bundle", lambda ctx, cam: type("B", (), {"meta": {
        "stage_p50": 4.0, "stage_p90": 6.0, "stage_max": 11.18, "sigma_ft": 0.87}})())
    return calls


def test_out_of_range_fresh_gauge_trusts_gauge_never_quarantines(monkeypatch):
    canned_range(monkeypatch, get_gauge={"latest_ft": 17.1, "age_min": 0.0, "above_camera_range": True, "change_1h_ft": 0.2},
                 get_nws_forecast={"available": False}, render_wet_overlay={"overlay_key": "ov"})
    d = rules.decide(ev(["OUT_OF_RANGE", "DISAGREE", "RISING"]), CTX())
    assert "QUARANTINE" not in acts(d) and "DRAFT_ALERT" in acts(d) and d["camera_status"] == "saturated"


def test_out_of_range_stale_gauge_publishes_lower_bound(monkeypatch):
    canned_range(monkeypatch, get_gauge={"latest_ft": 16.9, "age_min": 240.0})
    d = rules.decide(ev(["OUT_OF_RANGE", "GAUGE_STALE"]), CTX())
    mp = next(a for a in d["actions"] if a["type"] == "MARK_PROVISIONAL")
    assert mp["args"] == {"source": "camera_lower_bound", "stage_ft": 11.18, "bound": "lower"}


def test_disagree_with_gauge_above_range_is_saturation_not_fault(monkeypatch):
    canned_range(monkeypatch, get_gauge={"latest_ft": 17.1, "age_min": 5.0, "above_camera_range": True},
                 image_quality={"usable": False, "issues": ["texture_loss"]})
    d = rules.decide(ev(["DISAGREE"]), CTX())
    assert acts(d) == {"NOOP"} and d["camera_status"] == "saturated"


def test_gauge_stale_camera_at_ceiling_gives_lower_bound_not_number(monkeypatch):
    canned_range(monkeypatch, image_quality=GOOD_Q, get_gauge={"latest_ft": 9.0, "age_min": 900.0},
                 estimate_stage={"ok": True, "stage_ft": 10.6, "sigma_ft": 0.87, "in_calibrated_range": True,
                                 "near_ceiling": True, "stage_max_ft": 11.18})
    d = rules.decide(ev(["GAUGE_STALE"]), CTX())
    assert next(a for a in d["actions"] if a["type"] == "MARK_PROVISIONAL")["args"]["source"] == "camera_lower_bound"


def test_muddy_water_during_rise_is_not_a_camera_fault(monkeypatch):
    canned_range(monkeypatch, image_quality={"usable": False, "issues": ["texture_loss", "fog"]},
                 get_gauge={"latest_ft": 5.0, "age_min": 0.0, "change_1h_ft": 0.3, "max_step_ft": 0.05, "step_isolation": 1},
                 estimate_stage={"ok": True, "stage_ft": 5.1, "sigma_ft": 0.3}, get_nws_forecast={"available": False})
    d = rules.decide(ev(["RISING", "DISAGREE", "LOW_QUALITY"], recent_flags=[["LOW_QUALITY"], ["LOW_QUALITY"]]), CTX())
    assert not acts(d) & {"QUARANTINE", "OPEN_TICKET"}


# ---- guard rails ----

def test_finalize_enforces_approval_and_drops_unknown_actions():
    d = schema.new_decision({"event_id": "x"}, "llm")
    d["actions"] = [{"type": "DRAFT_ALERT", "args": {}, "needs_approval": False}, {"type": "SEND_EMAIL"},
                    {"type": "NOOP"}, {"type": "DRAFT_ALERT"}]
    d = schema.finalize({"event_id": "x"}, d)
    assert schema.action_types(d) == ["DRAFT_ALERT"] and d["actions"][0]["needs_approval"]
    assert d["approval_id"] and "SEND_EMAIL" in d["rationale"]


def test_kill_switch_and_audit_log(tmp_path, monkeypatch):
    sink = Sink(local_dir=tmp_path, bucket="")
    sink.put_bytes("live/agent/ENABLED", b"false")
    e = ev(["RISING"], mode="live")
    d = agent.handle(e, ctx=tools.ToolContext(sink=sink), write_log=True)
    assert d["decided_by"] == "kill_switch" and schema.action_types(d) == ["NOOP"]
    logs = list((tmp_path / "live" / "agent").glob("*.jsonl"))
    assert logs and "kill_switch" in logs[0].read_text()


def test_alert_hysteresis_suppresses_repeat_drafts(tmp_path, monkeypatch):
    sink = Sink(local_dir=tmp_path, bucket="")
    out = []
    for hour, stage in ((0, 6.5), (1, 6.6), (2, 7.2), (20, 6.7)):
        canned(monkeypatch, get_gauge={"latest_ft": stage, "age_min": 0.0, "change_1h_ft": 0.0},
               get_nws_forecast={"available": False}, render_wet_overlay={"overlay_key": "ov"})
        e = ev(["RISING"], mode="replay")
        e["reading"]["t_frame"] = (pd.Timestamp("2026-07-29T00:00Z") + pd.Timedelta(hours=hour)).isoformat()
        out.append(agent.handle(e, ctx=tools.ToolContext(sink=sink), use_llm=False))
    has = ["DRAFT_ALERT" in schema.action_types(d) for d in out]
    assert has == [True, False, True, True]          # first, suppressed, +0.7 ft higher, after the 12 h hold
    assert out[1]["approval_id"] is None and "duplicate suppressed" in out[1]["rationale"]


def test_token_cap_falls_back_to_rules(tmp_path, monkeypatch):
    canned(monkeypatch, get_gauge={"latest_ft": 4.2, "age_min": 15, "change_1h_ft": 0.1}, get_nws_forecast={"available": False})
    sink = Sink(local_dir=tmp_path, bucket="")
    monkeypatch.setattr(llm, "DAILY_TOKENS", 10)
    llm.TokenLedger(sink, 10).add(50, 0.0)
    boom = lambda **kw: pytest.fail("Bedrock must not be called past the token cap")   # noqa: E731
    d = agent.handle(ev(["RISING"], mode="live"), ctx=tools.ToolContext(sink=sink), converse=boom)
    assert d["decided_by"] == "rules" and d["fallback_reason"] == "token_cap"


# ---- LLM loop on a fake Bedrock ----

def fake_bedrock(script):
    """script: list of assistant contents; returns a converse() that replays them and records requests."""
    seen = []

    def converse(**kw):
        seen.append(copy.deepcopy(kw))
        content = script[min(len(seen) - 1, len(script) - 1)]
        stop = "tool_use" if any("toolUse" in c for c in content) else "end_turn"
        return {"output": {"message": {"role": "assistant", "content": content}}, "stopReason": stop,
                "usage": {"inputTokens": 1000, "outputTokens": 100}}
    return converse, seen


def test_llm_loop_runs_tools_and_submits(monkeypatch):
    calls = canned(monkeypatch, image_quality={"usable": True, "issues": []})
    conv, seen = fake_bedrock([
        [{"text": "checking"}, {"toolUse": {"toolUseId": "t1", "name": "image_quality", "input": {"frame_key": "k.jpg"}}}],
        [{"toolUse": {"toolUseId": "t2", "name": "submit_decision", "input": {
            "actions": [{"type": "DRAFT_ALERT", "args": {"stage_ft": 6}}], "rationale": "high water"}}}],
    ])
    d = llm.run(ev(["RISING"]), CTX(), converse=conv)
    assert calls == ["image_quality"] and d["decided_by"] == "llm"
    assert schema.action_types(d) == ["DRAFT_ALERT"] and d["actions"][0]["needs_approval"] and d["approval_id"]
    assert d["tokens_in"] == 2000 and d["usd"] > 0 and "temperature" not in seen[0]["inferenceConfig"]
    # the tool result went back to the model in the next request
    assert seen[1]["messages"][-1]["content"][0]["toolResult"]["toolUseId"] == "t1"


def test_llm_tool_budget_is_enforced(monkeypatch):
    calls = canned(monkeypatch)
    loop = [{"toolUse": {"toolUseId": f"t{i}", "name": "get_gauge", "input": {}}} for i in range(12)]
    conv, _ = fake_bedrock([loop, [{"toolUse": {"toolUseId": "s", "name": "submit_decision",
                                                "input": {"actions": [{"type": "NOOP"}], "rationale": "x"}}}]])
    d = llm.run(ev(["RISING"]), CTX(), converse=conv)
    assert len(calls) == llm.MAX_TOOL_CALLS and d["n_tool_calls"] == 12


def test_bedrock_throttle_is_retried_not_fallen_back(monkeypatch):
    """Regression (pilot, Oct 23): 3/12 decisions fell back to rules on ThrottlingException at a 10 RPM quota."""
    from botocore.exceptions import ClientError
    calls = []

    class Fake:
        def converse(self, **kw):
            calls.append(1)
            if len(calls) < 3:
                raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "Converse")
            return {"ok": True}
    monkeypatch.setattr(llm, "_client", Fake())
    monkeypatch.setattr(llm, "THROTTLE_BACKOFF_S", (0, 0, 0))
    monkeypatch.setattr(llm, "RPM", 1e6)
    assert llm.bedrock_converse(modelId="m") == {"ok": True} and len(calls) == 3


def test_llm_failure_falls_back_to_rules(monkeypatch):
    canned(monkeypatch, get_gauge={"latest_ft": 4.2, "age_min": 15, "change_1h_ft": 0.1}, get_nws_forecast={"available": False})

    def broken(**kw):
        raise RuntimeError("AccessDeniedException")
    d = agent.handle(ev(["RISING"]), ctx=CTX(), converse=broken)
    assert d["decided_by"] == "rules" and "AccessDenied" in d["fallback_reason"]


def test_sonnet_second_opinion_recorded_when_escalating(monkeypatch):
    canned(monkeypatch)
    monkeypatch.setenv("RIVERSIGHT_AGENT_ESCALATE", "1")
    submit = lambda acts: [{"toolUse": {"toolUseId": "s", "name": "submit_decision",          # noqa: E731
                                        "input": {"actions": [{"type": a} for a in acts], "rationale": "r"}}}]

    def conv(**kw):
        acts = ["DENSIFY"] if "sonnet" in kw["modelId"] else ["DRAFT_ALERT"]
        return {"output": {"message": {"role": "assistant", "content": submit(acts)}}, "stopReason": "tool_use",
                "usage": {"inputTokens": 10, "outputTokens": 5}}
    d = agent.handle(ev(["RISING"]), ctx=CTX(), converse=conv)
    assert schema.action_types(d) == ["DRAFT_ALERT"] and d["second_opinion"]["agrees"] is False
    assert "Sonnet second opinion disagrees" in d["rationale"]


def test_flags_only_ablation_withholds_evidence():
    ctx = tools.ToolContext(evidence="flags_only", event=ev(["VIEW_CHANGE"]))
    r = tools.call(ctx, "estimate_stage", {"cam": "CAM", "frame_key": "k.jpg"})
    assert r["flags"] == ["VIEW_CHANGE"] and "stage_ft" not in r


# ---- gauge faults and synthetic frames ----

def test_gauge_faults():
    idx = pd.date_range("2026-10-05", periods=97, freq="15min", tz="UTC")
    g = pd.Series(np.linspace(5, 6, 97), index=idx)
    now = idx[-1]
    assert tools.apply_gauge_fault(g, now, {"kind": "dropout", "hours": 6}).index[-1] < now - pd.Timedelta(hours=5.9)
    off = tools.apply_gauge_fault(g, now, {"kind": "offset", "ft": 0.5, "hours": 2})
    assert off.iloc[-1] - g.iloc[-1] == pytest.approx(0.5) and off.iloc[0] == g.iloc[0]
    flat = tools.apply_gauge_fault(g, now, {"kind": "flatline", "hours": 8})
    assert flat.iloc[-1] == flat.iloc[-30]


def test_synthetic_faults_are_deterministic():
    img = (np.random.default_rng(0).random((180, 320, 3)) * 255).astype(np.uint8)
    for f in faults.FAULTS:
        a, b = faults.apply(img, f, 3), faults.apply(img, f, 3)
        assert a.shape == img.shape and np.array_equal(a, b) and not np.array_equal(a, img)


# ---- real OpenCV tools on cached data (skipped on a fresh clone) ----

BUNDLE = ROOT / "data" / "derived" / "agent_bundles" / "IL_Salt_Creek_at_Wood_Dale"


@pytest.mark.skipif(not BUNDLE.exists(), reason="needs local data + agent bundles")
def test_real_tools_on_cached_frame():
    cam = BUNDLE.name
    fn = "IL_Salt_Creek_at_Wood_Dale___2026-10-04T17-00-23Z.jpg"
    key = f"data/raw/720/{cam}/{fn}"
    ctx = tools.ToolContext(mode="eval", bundle_root=BUNDLE.parent, now=pd.Timestamp("2026-10-04T17:00:23Z"),
                            event={"cam_id": cam, "reading": {}}, write_overlays=False)
    est = tools.call(ctx, "estimate_stage", {"cam": cam, "frame_key": key})
    assert est["ok"] and abs(est["stage_ft"] - 8.5) < 3 * est["sigma_ft"]          # gauge read 8.50 ft
    assert tools.call(ctx, "image_quality", {"frame_key": key})["usable"]
    fog = tools.call(ctx, "image_quality", {"frame_key": faults.synth_key("fog", 1, key)})
    assert not fog["usable"] and "fog" in fog["issues"] and "ir_or_night" not in fog["issues"]
    assert "ir_or_night" in tools.call(ctx, "image_quality", {"frame_key": faults.synth_key("ir", 1, key)})["issues"]
