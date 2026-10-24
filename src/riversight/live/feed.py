"""Public read-only data feed (D-0013 W1-3), static JSON + Atom under /api/v1/ (CloudFront → S3).

  api/v1/sites.json                  every served camera: location, group, status, latest stage values
  api/v1/sites/<cam>/latest.json     the latest reading (public fields only)
  api/v1/sites/<cam>/history.json    the last 7 days, compact (refreshed hourly)
  api/v1/feed.xml                    Atom: flood-state changes and human-approved alerts

Written by the worker each cycle. Nothing is pushed anywhere: no email or webhooks to third parties.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

import pandas as pd

PREFIX = "api/v1"
PUBLIC = ("cam_id", "t_frame", "daylight", "camera_stage_ft", "camera_sigma_ft", "camera_at_least_ft",
          "calibrated_range_ft", "gauge_stage_ft", "gauge_time", "gauge_age_min", "flood_state", "flags", "status",
          "provisional", "overlay_key", "thumb_key", "model_sha", "fused_stage_ft", "fused_sigma_ft", "fused_source")
HIST = ("t_frame", "camera_stage_ft", "camera_sigma_ft", "camera_at_least_ft", "gauge_stage_ft", "flood_state", "flags")
HISTORY_EVERY_S = 55 * 60
SITE_URL = "https://d2aes2r6og8aap.cloudfront.net"


def _pub(r: dict) -> dict:
    out = {k: r.get(k) for k in PUBLIC if k in r}
    for k in ("overlay_key", "thumb_key"):
        if out.get(k):
            out[k.replace("_key", "_url")] = f"{SITE_URL}/{out.pop(k)}"
    return out


def flood_event(store, reading: dict, prev_state: str | None) -> None:
    """Append a flood-state change (normal ↔ elevated ↔ flood) to live/feed/events.jsonl."""
    fs = reading.get("flood_state")
    if prev_state is None or fs in (None, "unknown") or fs == prev_state:
        return
    store.append_jsonl("live/feed/events.jsonl", {
        "kind": "flood_state", "cam_id": reading["cam_id"], "t": reading["t_frame"], "from": prev_state, "to": fs,
        "gauge_stage_ft": reading.get("gauge_stage_ft"), "camera_stage_ft": reading.get("camera_stage_ft"),
        "camera_at_least_ft": reading.get("camera_at_least_ft")})


def _recent_lines(store, key: str, n: int = 200) -> list[dict]:
    b = store.get_bytes(key) or b""
    out = []
    for ln in b.decode().splitlines()[-n:]:
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


def atom(entries: list[dict], updated: str) -> str:
    items = []
    for e in entries:
        items.append(
            f"<entry><id>urn:riversight:{escape(e['id'])}</id><title>{escape(e['title'])}</title>"
            f"<updated>{escape(e['t'])}</updated><link href=\"{escape(e['link'])}\"/>"
            f"<summary>{escape(e['summary'])}</summary></entry>")
    return ('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">'
            f"<id>urn:riversight:feed</id><title>RiverSight: flood-state changes and approved alerts</title>"
            f"<updated>{escape(updated)}</updated><link href=\"{SITE_URL}/api.html\"/>"
            f"<author><name>RiverSight (OpenCV AI Competition 2026 entry; not an official USGS product)</name></author>"
            + "".join(items) + "</feed>\n")


def build(store, models, idx: dict) -> None:
    now = datetime.now(timezone.utc)
    meta = {m.cam_id: m.meta for m in models}
    sites = []
    for s in idx.get("sites", []):
        cam = s["cam_id"]
        r = store.get_json(f"live/sites/{cam}/latest.json")
        m = meta.get(cam, {})
        pub = _pub(r) if r else {"cam_id": cam}
        store.put_json(f"{PREFIX}/sites/{cam}/latest.json", pub)
        sites.append({"cam_id": cam, "nwis_id": m.get("nwis_id"), "lat": m.get("lat"), "lon": m.get("lon"),
                      "group": "onboarded" if m.get("onboarded") else "frozen20", "tier": m.get("tier"),
                      "page": f"{SITE_URL}/site.html?cam={cam}", **{k: pub.get(k) for k in (
                          "t_frame", "status", "flood_state", "fused_stage_ft", "fused_sigma_ft", "fused_source",
                          "camera_stage_ft", "camera_sigma_ft", "camera_at_least_ft", "gauge_stage_ft")}})
    store.put_json(f"{PREFIX}/sites.json", {"generated_utc": now.isoformat(timespec="seconds"),
                                            "cycle_started": idx.get("cycle_started"), "n_sites": len(sites),
                                            "license": "data derived from USGS (public domain); images face-blurred",
                                            "schema": f"{SITE_URL}/api.html", "sites": sites})
    # 7-day history, hourly
    last = (store.get_json(f"{PREFIX}/history_meta.json") or {}).get("generated_utc")
    if not last or (now - pd.Timestamp(last).to_pydatetime()).total_seconds() >= HISTORY_EVERY_S:
        days = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
        for s in sites:
            rows = []
            for d in days:
                rows += [{k: r.get(k) for k in HIST} for r in _recent_lines(store, f"live/sites/{s['cam_id']}/{d}.jsonl", 2000)]
            store.put_json(f"{PREFIX}/sites/{s['cam_id']}/history.json",
                           {"cam_id": s["cam_id"], "days": 7, "readings": rows})
        store.put_json(f"{PREFIX}/history_meta.json", {"generated_utc": now.isoformat(timespec="seconds")})
    # Atom feed: flood-state changes + approved alerts (last 7 days)
    entries = []
    for e in _recent_lines(store, "live/feed/events.jsonl", 300):
        entries.append({"id": f"fs:{e['cam_id']}:{e['t']}", "t": e["t"], "link": f"{SITE_URL}/site.html?cam={e['cam_id']}",
                        "title": f"{e['cam_id']}: flood state {e['from']} → {e['to']}",
                        "summary": f"gauge {e.get('gauge_stage_ft')} ft; camera "
                                   f"{e.get('camera_stage_ft') if e.get('camera_stage_ft') is not None else ('>= ' + str(e.get('camera_at_least_ft')) if e.get('camera_at_least_ft') else 'n/a')} ft"})
    for i in range(7):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        for a in _recent_lines(store, f"live/agent/approvals-{d}.jsonl", 200):
            if a.get("status") != "approved" or not any(x.get("type") == "DRAFT_ALERT" for x in a.get("actions", [])):
                continue
            entries.append({"id": f"alert:{a['approval_id']}", "t": a.get("decided") or a.get("created"),
                            "link": f"{SITE_URL}/approvals.html#{a['approval_id']}",
                            "title": f"{a['cam_id']}: flood alert approved by the operator",
                            "summary": (a.get("rationale") or "")[:500]})
    entries.sort(key=lambda e: e["t"] or "", reverse=True)
    store.put_bytes(f"{PREFIX}/feed.xml", atom(entries[:100], now.isoformat(timespec="seconds")).encode(),
                    "application/atom+xml", "max-age=60")
