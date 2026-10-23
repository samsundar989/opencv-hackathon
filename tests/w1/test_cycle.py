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
    assert not cycle.due({"last_t": "2026-10-23T11:55:00Z"}, now)
    assert cycle.due({"last_t": "2026-10-23T11:45:00Z"}, now)


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


def _run(tmp_path, gauge_ft, gauge_age_h=0.25, state=None):
    m = SiteModel(BUNDLE)
    p = sorted(FRAMES.glob("*.jpg"))[len(list(FRAMES.glob("*.jpg"))) // 2]
    from riversight.data.nims import parse_filename
    t = parse_filename(p.name)[1]
    store = LocalStore(tmp_path)
    if state:
        store.put_json(f"live/state/{CAM}.json", state)
    g = cycle.Gauge({m.meta["nwis_id"]: pd.Series([gauge_ft], index=pd.DatetimeIndex([pd.Timestamp(t) - timedelta(hours=gauge_age_h)]))})
    r = cycle.run_site(m, cycle.Frame(p.name, t, cv2.imread(str(p))), store, g, t, {}, None, mode="eval")
    return m, r, store


@pytest.mark.skipif(not BUNDLE.exists() or not FRAMES.exists(), reason="bundles / frame cache not present")
def test_gauge_above_range_flags_out_of_range_and_disagree_immediately(tmp_path):
    m, r, _ = _run(tmp_path, gauge_ft=SiteModel(BUNDLE).meta["stage_max"] + 2.0)
    assert "OUT_OF_RANGE" in r["flags"] and "DISAGREE" in r["flags"]
    assert r["camera_stage_ft"] is None and r["camera_sigma_ft"] is None      # never a number above the range
    if r["daylight"] and r["registration"]["ok"]:
        assert r["camera_at_least_ft"] == round(m.meta["stage_max"], 3)
    assert r["status"] == "above_range"


@pytest.mark.skipif(not BUNDLE.exists() or not FRAMES.exists(), reason="bundles / frame cache not present")
def test_last_daylight_remembered(tmp_path):
    _, r, store = _run(tmp_path, gauge_ft=8.0)
    if r["daylight"] and r["registration"]["ok"]:
        st = store.get_json(f"live/state/{CAM}.json")
        assert st["last_daylight"]["frame_key"] == r["frame_key"] and r["last_daylight"]["H_frame_to_ref"]


@pytest.mark.skipif(not BUNDLE.exists() or not FRAMES.exists(), reason="bundles / frame cache not present")
def test_quarantine_released_after_three_good_cycles(tmp_path):
    _, r0, _ = _run(tmp_path / "probe", gauge_ft=8.0)
    if not (r0["daylight"] and r0["registration"]["ok"]):
        pytest.skip("probe frame not registrable")
    g = r0["camera_raw_ft"]                       # gauge agrees with the camera
    _, r, store = _run(tmp_path, g, state={"quarantined": {"since": "x"}, "release_run": 2})
    st = store.get_json(f"live/state/{CAM}.json")
    assert "quarantined" not in st and r["camera_stage_ft"] is not None
    assert any(a["type"] == "QUARANTINE_RELEASED" for d in store.list("live/agent/") for a in
               [x for line in (tmp_path / d).read_text().splitlines() for x in __import__("json").loads(line)["actions"]])
