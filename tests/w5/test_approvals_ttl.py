import pandas as pd

from riversight.live.approvals_ttl import expire_approvals, verdict
from riversight.live.store import LocalStore

NOW = pd.Timestamp("2026-10-26T12:00:00Z")


def item(**kw):
    return {"approval_id": "a", "status": "pending", "cam_id": "X", "created": "2026-10-26T06:00:00Z",
            "actions": [{"type": "OPEN_TICKET"}], **kw}


def test_verdicts():
    assert verdict(item(), NOW) is None                                            # 6 h old: stays
    assert verdict(item(created="2026-10-25T06:00:00Z"), NOW)[0] == "expired"      # 30 h old
    assert verdict(item(created=1729700000.0), NOW)[0] == "expired"               # float created (agent store) too
    assert verdict(item(created="2026-10-24T06:00:00Z", kind="onboard_request"), NOW) is None
    assert verdict(item(created="2026-10-24T06:00:00Z", status="approved"), NOW) is None
    mallard = item(cam_id="CA_First_Mallard_Branch_nr_Fairfield", actions=[{"type": "DRAFT_ALERT"}],
                   created="2026-10-24T18:15:04Z")
    assert verdict(mallard, NOW)[0] == "superseded"
    assert verdict(dict(mallard, created="2026-10-26T01:00:00Z"), NOW) is None    # after the fix: a real alert


def test_expire_writes_back_and_logs(tmp_path):
    s = LocalStore(tmp_path)
    s.put_json("live/approvals/a.json", item(created="2026-10-25T06:00:00Z"))
    s.put_json("live/approvals/b.json", item(approval_id="b"))
    assert expire_approvals(s, NOW) == 1
    assert s.get_json("live/approvals/a.json")["status"] == "expired"
    assert s.get_json("live/approvals/b.json")["status"] == "pending"
    assert (tmp_path / "live/agent/approvals-2026-10-26.jsonl").exists()
