"""NOAA NWPS flood categories and forecast crest per site (forecast flood picture, PLAN_2026-10-23 W1).

The worker refreshes live/nws/<cam>.json at most hourly (two small requests per site with an NWPS point).
The site page turns it into flood-category ticks on the stage slider and a "forecast crest" button that
draws the crest's connected wet area onto today's frame.
"""
from __future__ import annotations

import time
import traceback

import pandas as pd

NWPS = "https://api.water.noaa.gov/nwps/v1/gauges"
UA = {"User-Agent": "RiverSight/0.1 (OpenCV AI Competition 2026)"}
REFRESH_S = 55 * 60


def fetch_site(client, nwis_id: str) -> dict:
    g = client.get(f"{NWPS}/{nwis_id}")
    if g.status_code == 404:
        return {"available": False, "note": "no NWPS forecast point for this USGS gauge"}
    g.raise_for_status()
    gj = g.json()
    lid = gj.get("lid")
    cats = {k: v.get("stage") for k, v in ((gj.get("flood") or {}).get("categories") or {}).items()
            if v and v.get("stage") is not None and v.get("stage") > -9000}
    out = {"available": True, "lid": lid, "name": gj.get("name"), "flood_categories_ft": cats,
           "page": f"https://water.noaa.gov/gauges/{lid}" if lid else None, "forecast": None}
    f = client.get(f"{NWPS}/{lid}/stageflow/forecast")
    if f.status_code == 200:
        now = pd.Timestamp.now(tz="UTC") - pd.Timedelta("1h")
        pts = [(p.get("validTime"), p.get("primary")) for p in (f.json().get("data") or [])
               if p.get("primary") is not None and p.get("validTime") and pd.Timestamp(p["validTime"]) >= now]
        if pts:
            t, v = max(pts, key=lambda p: p[1])
            out["forecast"] = {"crest_ft": round(float(v), 2), "crest_time": t, "issued": f.json().get("issuedTime"),
                               "first": pts[0][0], "last": pts[-1][0], "n_points": len(pts)}
    return out


def refresh(store, models, force: bool = False) -> None:
    import httpx
    now = pd.Timestamp.now(tz="UTC")
    with httpx.Client(timeout=15, headers=UA, follow_redirects=True) as c:
        for m in models:
            key = f"live/nws/{m.cam_id}.json"
            old = store.get_json(key)
            if not force and old and (now - pd.Timestamp(old["fetched_utc"])).total_seconds() < REFRESH_S:
                continue
            try:
                d = fetch_site(c, m.meta["nwis_id"])
            except Exception as e:
                traceback.print_exc()
                d = {"available": False, "note": f"NWPS unavailable ({type(e).__name__})"}
            d["fetched_utc"] = now.isoformat()
            d["calibrated_range_ft"] = [m.meta["stage_min"], m.meta["stage_max"]]
            store.put_json(key, d)
            time.sleep(0.3)
