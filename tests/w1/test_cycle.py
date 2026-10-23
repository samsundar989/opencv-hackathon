"""W1: live cycle — one cached frame through run_site into a LocalStore (no network), flags, agent hook."""
from datetime import timedelta
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import pytest

from riversight.live import cycle
from riversight.live.bundle import SiteModel
from riversight.live.store import LocalStore

ROOT = Path(__file__).resolve().parents[2]
CAM = "TX_Clear_Fk_Trinity_Rv_at_Ft_Worth"
BUNDLE = ROOT / "models" / "sites" / CAM
FRAMES = ROOT / "data" / "raw" / "720" / CAM


def test_clean_mask_drops_specks():
    m = np.zeros((45, 80), bool)
    m[10:14, 10:14] = True      # 16-block blob stays
    m[30, 50] = True            # single speck goes
    out = cycle.clean_mask(m)
    assert out[11, 11] == 255 and out[30, 50] == 0


def test_flood_state_and_due():
    meta = {"flood_elevated_ft": 4.0, "flood_ft": 5.0}
    assert [cycle.flood_state(s, meta) for s in (3.0, 4.2, 6.0, None)] == ["normal", "elevated", "flood", "unknown"]
    now = pd.Timestamp("2026-10-23T12:00:00Z").to_pydatetime()
    assert cycle.due(None, now)
    assert not cycle.due({"last_t": "2026-10-23T11:45:00Z"}, now)
    assert cycle.due({"last_t": "2026-10-23T11:45:00Z", "densify_until": "2026-10-23T18:00:00Z"}, now)


@pytest.mark.skipif(not BUNDLE.exists() or not FRAMES.exists(), reason="bundles / frame cache not present")
def test_run_site_writes_reading_and_calls_agent_on_flags(tmp_path):
    m = SiteModel(BUNDLE)
    p = sorted(FRAMES.glob("*.jpg"))[len(list(FRAMES.glob("*.jpg"))) // 2]
    from riversight.data.nims import parse_filename
    t = parse_filename(p.name)[1]
    store = LocalStore(tmp_path)
    calls = []

    def agent(ev):
        calls.append(ev)
        return {"decided_by": "test", "actions": [{"type": "DRAFT_ALERT", "args": {}, "needs_approval": True}],
                "rationale": "test"}

    # gauge 3 h stale → GAUGE_STALE → agent called → approval written
    g = cycle.Gauge({m.meta["nwis_id"]: pd.Series([1.0], index=pd.DatetimeIndex([pd.Timestamp(t) - timedelta(hours=3)]))})
    r = cycle.run_site(m, cycle.Frame(p.name, t, cv2.imread(str(p))), store, g, t, {}, agent, mode="eval")
    assert "GAUGE_STALE" in r["flags"]
    assert store.get_json(f"live/sites/{CAM}/latest.json")["t_frame"] == r["t_frame"]
    assert store.get_bytes(r["overlay_key"]) and store.get_bytes(r["frame_key"])
    assert len(calls) == 1 and calls[0]["reading"]["cam_id"] == CAM
    assert r["agent"]["approval_id"] and store.list("live/approvals/")
    if r["daylight"] and r["registration"]["ok"]:
        assert r["camera_stage_ft"] is not None and r["status"] == "provisional"
