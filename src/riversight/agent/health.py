"""Fleet camera-health QA for operators (D-0013 W2-3) → `live/agent/health.json`.

USGS runs ~1,300 HIVIS cameras and nobody watches them. Every cycle (or once a day) this reads each site's recent
readings from the live store and reports, per camera, what an operator should fix:

  offline           no new frame for > 6 h while the sun is up (Pecatonica has uploaded nothing since Oct 20)
  view_changed      ≥ half of the last 24 h of daylight frames fail registration (re-aimed / moved / blocked)
  ir_stuck_on       ≥ half of the last 24 h of frames with the sun ≥ 10° up are NIGHT-flagged AND those frames are
                    monochrome (chroma < 1; snow and grey sky fool the saturation test, not this one)
  lens_degradation  daily median sharpness < half the camera's own trailing 14-day baseline, or haze > baseline +
                    0.12, on ≥ 2 of the last 3 days and not improving (dirt, spider web, condensation); silent until
                    7 baseline days exist
  gauge_vs_camera   over ≥ 6 daylight readings in 72 h the camera sits > 2.5 σ from the gauge on the same side
                    while the camera registers well — check the gauge (drift) or recalibrate the camera

Every finding is a **ticket draft that needs human approval** (nothing is sent anywhere by this module), with the
numbers behind it and the frame/overlay keys an operator can open. Readings at night, out of calibrated range or
quarantined are excluded from the checks they would bias.

    from riversight.agent.health import write_health; write_health(store)      # W1: end of cycle or daily
    python -m riversight.agent.health --s3 <bucket> | --local live_local [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

OFFLINE_H = 6.0
DAY_SUN_DEG = 10.0
VIEW_SHARE = 0.5
IR_SHARE = 0.5
DISAGREE_SIGMAS, DISAGREE_MIN_N = 2.5, 6
IR_CHROMA = 1.0          # mean |R-G| + |G-B| below this = a monochrome (IR) frame
LENS_BASELINE_DAYS, LENS_MIN_BASELINE = 14, 7
LENS_LAP_RATIO, LENS_FOG_RISE = 0.5, 0.12


def chroma(img) -> float:
    """Mean |R-G| + |G-B| below the USGS overlay band: exactly 0 for a monochrome IR frame."""
    im = img[56:].astype(np.int16)
    return float(np.mean(np.abs(im[..., 2] - im[..., 1])) + np.mean(np.abs(im[..., 1] - im[..., 0])))


def frame_chroma(fetch, key: str | None) -> float | None:
    if not key or fetch is None:
        return None
    import cv2
    b = fetch(key)
    img = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR) if b else None
    return None if img is None else chroma(img)


def lens_flags(rows: list[tuple[str, float, float]]) -> list[dict]:
    """rows: (day, median sharpness, median haze) in day order. A day is bad when sharpness < LENS_LAP_RATIO × the
    trailing baseline median or haze > baseline + LENS_FOG_RISE; flagged when >= 2 of the last 3 days are bad, the
    latest is bad, and it is not improving. Needs >= LENS_MIN_BASELINE baseline days (silent before that)."""
    out = []
    for i in range(len(rows)):
        base = rows[max(0, i - 2 - LENS_BASELINE_DAYS):max(0, i - 2)]
        if len(base) < LENS_MIN_BASELINE:
            continue
        bl, bf = float(np.median([r[1] for r in base])), float(np.median([r[2] for r in base]))
        w = rows[i - 2:i + 1] if i >= 2 else []
        if len(w) < 3:
            continue
        bad = [(lv < LENS_LAP_RATIO * bl) or (fg > bf + LENS_FOG_RISE) for _, lv, fg in w]
        worse = w[-1][1] <= w[0][1] or w[-1][2] >= w[0][2]
        if sum(bad) >= 2 and bad[-1] and worse:
            out.append({"day": w[-1][0], "bad_days": int(sum(bad)), "median_lap_var": [round(r[1]) for r in w],
                        "median_fog": [round(r[2], 3) for r in w], "baseline_lap_var": round(bl), "baseline_fog": round(bf, 3)})
    return out


def _ts(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _readings(store, cam: str, now: datetime, days: int) -> list[dict]:
    out = []
    for k in range(days, -1, -1):
        day = (now - timedelta(days=k)).strftime("%Y-%m-%d")
        raw = store.get_bytes(f"live/sites/{cam}/{day}.jsonl") or b""
        for line in raw.decode("utf-8", "replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            t = _ts(r.get("t_frame"))
            if t and now - t <= timedelta(days=days):
                out.append(r)
    seen, uniq = set(), []
    for r in sorted(out, key=lambda r: r["t_frame"]):          # a frame can be re-read by several cycles
        if r["t_frame"] not in seen:
            seen.add(r["t_frame"])
            uniq.append(r)
    return uniq


def _issue(check: str, severity: int, summary: str, evidence: dict, images: list, ticket: str) -> dict:
    return {"check": check, "severity": severity, "summary": summary, "evidence": evidence,
            "images": [k for k in images if k],
            "ticket_draft": {"kind": check, "text": ticket, "needs_approval": True, "sent": False}}


def site_health(cam: str, latest: dict, rs: list[dict], meta: dict | None, now: datetime, fetch=None) -> list[dict]:
    issues = []
    meta = meta or {}
    imgs = [latest.get("frame_key"), latest.get("overlay_key") or latest.get("last_daylight_overlay_key")]
    # offline: sun is up now and the newest frame is old
    age_h = (latest.get("frame_age_min") or 0) / 60
    if (latest.get("sun_elev_deg") or -90) >= DAY_SUN_DEG - 5 or latest.get("daylight"):
        if age_h > OFFLINE_H:
            issues.append(_issue("offline", 3, f"no new frame for {age_h:.0f} h in daylight (last {latest.get('t_frame')})",
                                 {"frame_age_h": round(age_h, 1), "last_frame": latest.get("t_frame")}, imgs,
                                 f"Camera {cam} has not uploaded a frame for {age_h:.0f} h during daylight. "
                                 "Check power/network or the NIMS upload."))
    day = [r for r in rs if (r.get("sun_elev_deg") or -90) >= DAY_SUN_DEG and _ts(r["t_frame"]) >= now - timedelta(hours=24)]
    if len(day) >= 4:
        vc = np.mean(["VIEW_CHANGE" in (r.get("flags") or []) for r in day])
        if vc >= VIEW_SHARE:
            issues.append(_issue("view_changed", 3, f"{vc:.0%} of {len(day)} daylight frames in 24 h do not register to the reference",
                                 {"share_unregistered": round(float(vc), 2), "n": len(day)}, imgs,
                                 f"Camera {cam} appears re-aimed, moved or blocked: {vc:.0%} of today's frames fail "
                                 "registration. Confirm the view; re-anchor or recalibrate."))
        cand = [r for r in day if "NIGHT" in (r.get("flags") or [])]
        ir = len(cand) / len(day)
        if ir >= IR_SHARE:
            # the NIGHT pixel test also fires on snow / grey sky; a real IR frame is monochrome in the sensor (chroma
            # exactly 0 on all 6 live cameras checked at 05Z vs 10-38 by day and 3.5-5.7 on snow), so confirm on pixels
            chs = [c for c in (frame_chroma(fetch, r.get("frame_key")) for r in cand[-3:]) if c is not None]
            if chs and float(np.median(chs)) < IR_CHROMA:
                issues.append(_issue("ir_stuck_on", 2, f"{ir:.0%} of {len(day)} frames with the sun >= {DAY_SUN_DEG:.0f} deg are "
                                     f"monochrome IR frames (chroma {float(np.median(chs)):.2f})",
                                     {"share_ir_in_daylight": round(float(ir), 2), "n": len(day), "median_chroma": round(float(np.median(chs)), 3)},
                                     imgs, f"Camera {cam} seems stuck in IR/night mode during the day. Check the IR-cut filter "
                                     "or the day/night setting."))
    # lens degradation: daily medians vs the camera's OWN trailing 14-day baseline (calibration-season p-levels flag
    # every leaf-off / snowy day: 2-3 of 12 flagged days were real in the history spot check of v1)
    by_day: dict[str, list] = {}
    for r in rs:
        if (r.get("sun_elev_deg") or -90) >= DAY_SUN_DEG and r.get("quality"):
            by_day.setdefault(r["t_frame"][:10], []).append(r["quality"])
    rows = [(d, float(np.median([q["lap_var"] for q in by_day[d]])), float(np.median([q["fog_score"] for q in by_day[d]])))
            for d in sorted(by_day)]
    fl = lens_flags(rows)
    if fl and fl[-1]["day"] == rows[-1][0]:
        f = fl[-1]
        issues.append(_issue("lens_degradation", 2, f"sharpness/haze off this camera's own 14-day baseline on {f['bad_days']} of the last 3 days",
                             f, imgs, f"Camera {cam}: image sharpness has dropped / haze has risen for days compared with its "
                             "own recent baseline. Likely dirt, a spider web or condensation on the lens or housing; schedule a cleaning visit."))
    # persistent camera vs gauge disagreement on registered, in-range daylight readings
    sig = float(meta.get("sigma_ft") or latest.get("camera_sigma_ft") or 0.0)
    pairs = [r for r in rs if r.get("camera_stage_ft") is not None and r.get("gauge_stage_ft") is not None
             and (r.get("registration") or {}).get("ok") and "OUT_OF_RANGE" not in (r.get("flags") or [])
             and r.get("camera_at_least_ft") is None]
    if sig > 0 and len(pairs) >= DISAGREE_MIN_N:
        res = np.array([r["camera_stage_ft"] - r["gauge_stage_ft"] for r in pairs])
        med = float(np.median(res))
        same_side = np.mean(np.sign(res) == np.sign(med))
        if abs(med) > DISAGREE_SIGMAS * sig and same_side >= 0.8:
            issues.append(_issue("gauge_vs_camera", 3,
                                 f"camera sits {med:+.2f} ft from the gauge over {len(pairs)} registered readings (sigma {sig:.2f})",
                                 {"median_camera_minus_gauge_ft": round(med, 3), "sigma_ft": round(sig, 3), "n": len(pairs),
                                  "share_same_side": round(float(same_side), 2)}, imgs,
                                 f"Camera {cam} and its USGS gauge disagree by {med:+.2f} ft for days while the camera "
                                 "registers well. Check the gauge for drift or a datum change; otherwise recalibrate the camera."))
    return issues


def site_meta(store, cam: str) -> dict | None:
    """meta.json from the store, else from the local bundle dirs (the worker ships bundles on disk, not in S3)."""
    import os
    from pathlib import Path
    for key in (f"models/sites/{cam}/meta.json", f"models/onboard/{cam}/meta.json"):
        m = store.get_json(key)
        if m:
            return m
    root = Path(__file__).resolve().parents[3]
    for d in (Path(os.environ.get("RIVERSIGHT_BUNDLES", root / "models" / "sites")), root / "models" / "onboard"):
        p = d / cam / "meta.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return None


def build_health(store, now: datetime | None = None, days: int = 3) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    idx = store.get_json("live/index.json") or {}
    sites, n_issues = [], 0
    for s in idx.get("sites", []):
        cam = s.get("cam_id")
        latest = store.get_json(f"live/sites/{cam}/latest.json") or s
        meta = site_meta(store, cam)
        iss = site_health(cam, latest, _readings(store, cam, now, max(days, LENS_BASELINE_DAYS + 3)), meta, now,
                          fetch=store.get_bytes)
        n_issues += len(iss)
        sites.append({"cam_id": cam, "ok": not iss, "issues": iss, "last_frame": latest.get("t_frame")})
    sites.sort(key=lambda x: (-max([i["severity"] for i in x["issues"]] or [0]), x["cam_id"]))
    return {"generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "window_days": days, "n_sites": len(sites),
            "n_sites_with_issues": sum(not x["ok"] for x in sites), "n_issues": n_issues,
            "note": "ticket drafts only; each needs operator approval before anything is sent",
            "checks": ["offline", "view_changed", "ir_stuck_on", "lens_degradation", "gauge_vs_camera"], "sites": sites}


def write_health(store, now: datetime | None = None) -> dict[str, Any]:
    h = build_health(store, now)
    store.put_json("live/agent/health.json", h)
    store.put_json(f"live/agent/health/{h['generated_utc'][:10]}.json", h)
    return h


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m riversight.agent.health")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--s3", metavar="BUCKET")
    g.add_argument("--local", metavar="DIR")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    from pathlib import Path
    from riversight.live.store import LocalStore, S3Store
    store = S3Store(a.s3) if a.s3 else LocalStore(Path(a.local))
    t0 = time.time()
    h = build_health(store) if a.dry_run else write_health(store)
    print(json.dumps({k: h[k] for k in ("generated_utc", "n_sites", "n_sites_with_issues", "n_issues")}),
          f"({time.time() - t0:.1f} s)")
    for s in h["sites"]:
        for i in s["issues"]:
            print(f"  [{i['severity']}] {s['cam_id'][:45]:45s} {i['check']:16s} {i['summary']}")


if __name__ == "__main__":
    main()
