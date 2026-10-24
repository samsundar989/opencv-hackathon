"""W1: public feed — sites.json, per-site latest (public fields only), valid Atom with flood-state changes + approved alerts."""
import json
import xml.etree.ElementTree as ET
from types import SimpleNamespace

from riversight.live import feed
from riversight.live.store import LocalStore


def test_feed_build(tmp_path):
    st = LocalStore(tmp_path)
    r = {"cam_id": "A", "t_frame": "2026-10-24T15:00:00Z", "camera_stage_ft": 5.0, "gauge_stage_ft": 5.1,
         "flood_state": "elevated", "flags": [], "status": "ok", "overlay_key": "live/overlays/A/x.jpg",
         "registration": {"H_frame_to_ref": [1] * 9}, "quality": {"lap_var": 1}}
    st.put_json("live/sites/A/latest.json", r)
    feed.flood_event(st, r, "normal")
    feed.flood_event(st, r, "elevated")                       # no change → no event
    from datetime import datetime, timezone
    d = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    st.append_jsonl(f"live/agent/approvals-{d}.jsonl", {"approval_id": "apr-1", "status": "approved", "cam_id": "A",
                    "decided": "2026-10-24T15:05:00Z", "actions": [{"type": "DRAFT_ALERT"}], "rationale": "rising <fast> & high"})
    m = SimpleNamespace(cam_id="A", meta={"nwis_id": "1", "lat": 1.0, "lon": 2.0, "tier": "B"})
    feed.build(st, [m], {"cycle_started": "2026-10-24T15:00:00Z", "sites": [{"cam_id": "A"}]})
    sites = st.get_json("api/v1/sites.json")
    assert sites["n_sites"] == 1 and sites["sites"][0]["group"] == "frozen20"
    latest = st.get_json("api/v1/sites/A/latest.json")
    assert "registration" not in latest and latest["overlay_url"].endswith("live/overlays/A/x.jpg")
    root = ET.fromstring(st.get_bytes("api/v1/feed.xml"))
    titles = [e.text for e in root.iter("{http://www.w3.org/2005/Atom}title")]
    assert any("normal → elevated" in t for t in titles) and any("approved" in t for t in titles)
    assert st.get_json("api/v1/sites/A/history.json")["cam_id"] == "A"
