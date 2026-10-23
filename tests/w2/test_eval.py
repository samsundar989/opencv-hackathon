"""W2 eval harness: scoring rules and the fleet rank metric."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from riversight.agent import fleet, schema

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("agent_eval", ROOT / "scripts" / "agent_eval.py")
ae = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ae)


def dec(*acts, **args):
    d = schema.new_decision({"event_id": "e"}, "rules")
    d["actions"] = [schema.action(a, **args.get(a, {})) for a in acts]
    return schema.finalize({"event_id": "e"}, d)


def test_score_required_forbidden_and_args():
    ep = {"expected_actions": ["MARK_PROVISIONAL"], "forbidden_actions": ["QUARANTINE"],
          "expected_args": {"MARK_PROVISIONAL": {"source": "camera"}}}
    assert ae.score(ep, dec("MARK_PROVISIONAL", "DENSIFY", MARK_PROVISIONAL={"source": "camera"}))["success"]
    assert not ae.score(ep, dec("MARK_PROVISIONAL", MARK_PROVISIONAL={"source": "last_known"}))["success"]
    s = ae.score(ep, dec("MARK_PROVISIONAL", "QUARANTINE", MARK_PROVISIONAL={"source": "camera"}))
    assert not s["success"] and s["forbidden_hit"] == "QUARANTINE"


def test_score_control_counts_unneeded_escalations():
    ep = {"expected_actions": [], "forbidden_actions": ["OPEN_TICKET", "QUARANTINE"], "expected_args": {}}
    assert ae.score(ep, dec("NOOP"))["success"]
    s = ae.score(ep, dec("OPEN_TICKET", OPEN_TICKET={"kind": "gauge_suspect"}))
    assert not s["success"] and s["unneeded_escalations"] == 1


def test_kendall_tau():
    assert ae.kendall_tau(list("abcd"), list("abcd")) == 1.0
    assert ae.kendall_tau(list("dcba"), list("abcd")) == -1.0


def test_fleet_rules_ranking_orders_by_action_severity():
    items = [{"key": "quiet", "event": {"reading": {}, "site_meta": {}}, "decision": dec("NOOP")},
             {"key": "alert", "event": {"reading": {}, "site_meta": {}}, "decision": dec("DENSIFY", "DRAFT_ALERT")},
             {"key": "gauge", "event": {"reading": {}, "site_meta": {}},
              "decision": dec("OPEN_TICKET", OPEN_TICKET={"kind": "gauge_suspect"})},
             {"key": "moved", "event": {"reading": {}, "site_meta": {}}, "decision": dec("QUARANTINE")}]
    assert fleet.rank_rules(items)["order"] == ["alert", "gauge", "moved", "quiet"]
