"""W2 live fleet triage: ranking, reasons, evidence and grouping over a W1 LocalStore."""
from __future__ import annotations

from riversight.agent.triage import build_triage, write_triage
from riversight.live.store import LocalStore


def site(cam, status, flags, **kw):
    return {"cam_id": cam, "status": status, "flags": flags, **kw}


def test_triage_ranks_alert_first_groups_duplicates_and_carries_evidence(tmp_path):
    st = LocalStore(tmp_path)
    st.put_json("live/index.json", {"cycle_started": "2026-10-24T02:00:00Z", "sites": [
        site("QUIET", "night", ["NIGHT"]),
        site("OK", "ok", []),
        site("MOVED", "quarantined", ["VIEW_CHANGE"]),
        site("FLOOD", "ok", ["RISING", "OUT_OF_RANGE"], gauge_stage_ft=8.4, camera_at_least_ft=4.57)]})
    st.put_json("live/sites/FLOOD/latest.json", {"cam_id": "FLOOD", "status": "ok", "flags": ["RISING", "OUT_OF_RANGE"],
                                                 "gauge_stage_ft": 8.4, "camera_at_least_ft": 4.57,
                                                 "registration": {"ok": True, "inliers": 212, "inlier_ratio": 0.58},
                                                 "quality": {"lap_var": 900.0, "fog_score": 0.1, "glare_frac": 0.0}})
    st.put_json("live/sites/MOVED/latest.json", {"cam_id": "MOVED", "status": "quarantined", "flags": ["VIEW_CHANGE"],
                                                 "registration": {"ok": False, "inliers": 4}})
    for i, (cam, typ) in enumerate([("FLOOD", "DRAFT_ALERT"), ("MOVED", "OPEN_TICKET"), ("MOVED", "OPEN_TICKET")]):
        st.put_json(f"live/approvals/a{i}.json", {"approval_id": f"a{i}", "status": "pending", "cam_id": cam,
                                                  "created": f"2026-10-24T01:0{i}:00Z", "actions": [{"type": typ, "args": {"kind": "recalibration"}}]})
    st.put_json("live/approvals/done.json", {"approval_id": "done", "status": "approved", "cam_id": "OK", "actions": [{"type": "DRAFT_ALERT"}]})
    t = write_triage(st)
    assert [e["cam_id"] for e in t["ranked"]] == ["FLOOD", "MOVED"] and t["quiet"] == {"night": ["QUIET"], "ok": ["OK"]}
    top = t["ranked"][0]
    assert top["severity"] == 5 and top["needs"] == "flood alert awaiting approval"
    assert top["evidence"]["registration"]["inliers"] == 212 and top["evidence"]["camera_at_least_ft"] == 4.57
    moved = t["ranked"][1]["pending_approvals"]
    assert moved == [{"action": "OPEN_TICKET", "count": 2, "oldest": "2026-10-24T01:01:00Z", "newest": "2026-10-24T01:02:00Z",
                      "approval_id": "a2"}]
    assert st.get_json("live/agent/triage.json")["n_need_human"] == 2
