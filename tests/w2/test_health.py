"""W2 fleet camera-health QA (D-0013 W2-3): each check fires on its fault and stays quiet on a clean camera."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from riversight.agent.health import build_health
from riversight.live.store import LocalStore

NOW = datetime(2026, 10, 24, 21, 0, tzinfo=timezone.utc)
META = {"sigma_ft": 0.3, "quality": {"lap_var_p5": 1000.0, "fog_p95": 0.3}}


def reading(t, flags=(), lap=3000.0, fog=0.1, cam=5.0, gauge=5.0, reg=True, sun=30.0):
    return {"t_frame": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "sun_elev_deg": sun, "flags": list(flags), "daylight": sun > 0,
            "quality": {"lap_var": lap, "fog_score": fog, "glare_frac": 0.0}, "registration": {"ok": reg},
            "camera_stage_ft": cam, "gauge_stage_ft": gauge, "frame_key": "f.jpg"}


def put_site(st, cam, rows, latest_extra=None):
    by_day = {}
    for r in rows:
        by_day.setdefault(r["t_frame"][:10], []).append(r)
    for day, rs in by_day.items():
        st.put_bytes(f"live/sites/{cam}/{day}.jsonl", "\n".join(json.dumps(r) for r in rs).encode())
    latest = {**rows[-1], "frame_age_min": 5, **(latest_extra or {})}
    st.put_json(f"live/sites/{cam}/latest.json", latest)
    st.put_json(f"models/sites/{cam}/meta.json", META)


def hours(n, step=1):
    return [NOW - timedelta(hours=h) for h in range(n, 0, -step)]


def test_each_check_fires_on_its_fault_and_not_on_a_clean_camera(tmp_path):
    st = LocalStore(tmp_path)
    put_site(st, "CLEAN", [reading(t) for t in hours(70, 2)])
    put_site(st, "OFFLINE", [reading(t) for t in hours(70, 2)][:10], {"frame_age_min": 600, "sun_elev_deg": 30.0})
    put_site(st, "MOVED", [reading(t, flags=["VIEW_CHANGE"], reg=False) for t in hours(20)])
    put_site(st, "IR", [reading(t, flags=["NIGHT"]) for t in hours(20)])
    put_site(st, "DIRTY", [reading(t, lap=500.0 - 2 * i, fog=0.35) for i, t in enumerate(hours(70, 2))])
    put_site(st, "DRIFT", [reading(t, cam=5.0, gauge=6.2) for t in hours(70, 2)])
    st.put_json("live/index.json", {"sites": [{"cam_id": c} for c in ("CLEAN", "OFFLINE", "MOVED", "IR", "DIRTY", "DRIFT")]})
    h = build_health(st, now=NOW)
    found = {s["cam_id"]: [i["check"] for i in s["issues"]] for s in h["sites"]}
    assert found["CLEAN"] == []
    assert "offline" in found["OFFLINE"] and "view_changed" in found["MOVED"] and "ir_stuck_on" in found["IR"]
    assert "lens_degradation" in found["DIRTY"] and "gauge_vs_camera" in found["DRIFT"]
    tickets = [i["ticket_draft"] for s in h["sites"] for i in s["issues"]]
    assert tickets and all(t["needs_approval"] and not t["sent"] for t in tickets)
