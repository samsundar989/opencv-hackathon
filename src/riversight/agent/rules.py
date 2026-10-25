"""Deterministic River Steward policy: the Bedrock fallback and the evaluation baseline (arm b).

Same signature as `riversight.agent.handle`: Event -> Decision (INTERFACES §3). It calls the same OpenCV tools
as the LLM agent and maps their numbers to actions with fixed, hand-written thresholds:

  VIEW_CHANGE  transient (IR/night, blur, fog, glare)         -> NOOP, retry next frame
               registers to the current reference            -> NOOP (the homography absorbs the bump)
               registers to a calibrated banked reference    -> SET_REFERENCE
               no calibrated match                           -> QUARANTINE (+ OPEN_TICKET once it persists 3 cycles)
  GAUGE_STALE  usable frame + camera estimate in range        -> MARK_PROVISIONAL(camera) + DENSIFY
               otherwise                                     -> MARK_PROVISIONAL(last_known)
  DISAGREE     camera frame unusable / unregistrable          -> QUARANTINE (camera fault)
               camera agrees within 2σ on a fresh estimate    -> NOOP
               gauge jumped in isolation or is stuck flat     -> OPEN_TICKET gauge_suspect
               otherwise                                     -> QUARANTINE (the gauge is the reference instrument)
  RISING       always DENSIFY; stage ≥ site p90, NWS crest ≥ action stage, or fast rise above median
               -> wet overlays (now + projected crest) + DRAFT_ALERT
  LOW_QUALITY  persistent 3 cycles -> OPEN_TICKET lens check, else NOOP
  OUT_OF_RANGE (D-0009) the camera is saturated, not faulty: never a camera-only number
               fresh gauge -> trust the gauge, camera_status "saturated" (no QUARANTINE)
               stale gauge -> MARK_PROVISIONAL(camera_lower_bound, "≥ stage_max") + DENSIFY
  Saturation is also inferred inside DISAGREE / GAUGE_STALE: fresh gauge above the calibrated max, raw estimate
  within σ of the max, or the last known gauge (≤ 24 h) already at the max.
  While RISING, fog / texture loss alone do not make a frame unusable (muddy, bank-covering water is not fog).
  Tidal sites (agent/tidal_sites.json; D-0013 W2-1): RISING alerts only on water above the predicted tide (harmonic
  residual ≥ max(0.5 ft, 3σ)) or above the site's daily-maximum p99; an ordinary tide is a logged NOOP, unless the
  predicted tide for the next 24 h reaches the daily-max p99 -> TIDE_ADVISORY (low severity, approval; D-0014).
  RECALIBRATE (D-0014) on DISAGREE / OUT_OF_RANGE when W4's drift signal fires or a flood extended the calibrated
  range, and a refit bundle built on the served model exists (tool recal_status) -> approval; W4/W1 promote it.
"""
from __future__ import annotations

from typing import Any

from riversight.agent import schema, tools
from riversight.agent.schema import action

TRANSIENT = {"ir_or_night", "blurred", "fog", "glare"}
PERSIST_CYCLES = 2          # previous consecutive readings with the same flag → this one makes 3


def _run(ctx: tools.ToolContext, d: dict, name: str, **args) -> dict:
    res, ms = tools.timed_call(ctx, name, args)
    d["steps"].append({"tool": name, "args": args, "result_summary": res.get("summary", ""), "ms": ms})
    return res


def persisted(event: dict, flag: str, n: int = PERSIST_CYCLES) -> bool:
    rec = (event.get("recent") or [])[-n:]
    return len(rec) == n and all(flag in (r.get("flags") or []) for r in rec)


def _meta(ctx, cam) -> dict:
    try:
        return tools.bundle(ctx, cam).meta
    except Exception:                                                             # noqa: BLE001
        return {}


RISE_LENIENT = {"fog", "texture_loss"}


def rising_now(ev) -> bool:
    return "RISING" in (ev.get("reading", {}).get("flags") or [])


def usable(q: dict, ev: dict) -> bool:
    """image_quality verdict, except that during a rise turbid / bank-covering water (fog, texture loss) is not a fault."""
    issues = set(q.get("issues", []))
    if rising_now(ev):
        issues -= RISE_LENIENT
    return not issues


def fresh(g: dict) -> bool:
    return g.get("latest_ft") is not None and g.get("age_min") is not None and g["age_min"] <= 60


def saturation(meta: dict, est: dict | None, g: dict | None) -> str | None:
    """Why the camera is (or may be) above its calibrated range, or None."""
    smax, sig = meta.get("stage_max"), float(meta.get("sigma_ft") or 0.3)
    if smax is None:
        return None
    if g and fresh(g) and g["latest_ft"] > smax:
        return f"gauge {g['latest_ft']} ft is above the camera's calibrated max {smax:.2f} ft"
    if est and est.get("ok") and est.get("near_ceiling"):
        return f"camera estimate {est['stage_ft']} ft is at its calibrated ceiling {smax:.2f} ft"
    if g and g.get("latest_ft") is not None and g["latest_ft"] >= smax - sig:
        return f"last known gauge {g['latest_ft']} ft was already at the camera's calibrated max {smax:.2f} ft"
    return None


def out_of_range(ctx, ev, d, why):
    cam, key = ev["cam_id"], ev["reading"].get("frame_key")
    meta = _meta(ctx, cam)
    g = _run(ctx, d, "get_gauge", hours=24)
    smax = meta.get("stage_max")
    d["camera_status"] = "saturated"
    if fresh(g) and "GAUGE_STALE" not in (ev["reading"].get("flags") or []):
        why.append(f"camera above its calibrated range (max {smax} ft): saturated, not faulty; gauge {g['latest_ft']} ft trusted")
        return [action("NOOP", reason="camera_saturated", trust="gauge", gauge_ft=g["latest_ft"], camera_floor_ft=smax)]
    why.append(f"gauge stale and camera above its calibrated range: provisional lower bound >= {smax} ft")
    return [action("MARK_PROVISIONAL", source="camera_lower_bound", stage_ft=smax, bound="lower"),
            action("DENSIFY", minutes=15, hours=6)]


def view_change(ctx, ev, d, why):
    cam, key = ev["cam_id"], ev["reading"].get("frame_key")
    q = _run(ctx, d, "image_quality", frame_key=key)
    if TRANSIENT & set(q.get("issues", [])):
        why.append(f"view change looks transient ({', '.join(sorted(TRANSIENT & set(q['issues'])))}); retry next frame")
        return [action("NOOP", reason="transient", retry_next=True)]
    rr = _run(ctx, d, "reregister_fullres", cam=cam, frame_key=key)
    b = rr.get("best") or {}
    if b.get("ok") and b.get("ref") == "reference.jpg":
        why.append("frame still registers to the current reference; the homography absorbs the shift")
        return [action("NOOP", reason="registers_to_current")]
    if b.get("ok") and b.get("calibrated"):
        why.append(f"view matches banked calibrated reference {b['ref']}; re-anchoring")
        return [action("SET_REFERENCE", ref=b["ref"], inliers=b.get("inliers"))]
    out = [action("QUARANTINE", reason="view_change", until="recalibration")]
    if persisted(ev, "VIEW_CHANGE"):
        out.append(action("OPEN_TICKET", kind="recalibration", detail=rr.get("summary")))
        why.append("new or uncalibrated view persisted 3 cycles; quarantined and ticket opened for recalibration")
    else:
        why.append("frame matches no calibrated reference; readings quarantined")
    return out


def gauge_stale(ctx, ev, d, why):
    cam, key, r = ev["cam_id"], ev["reading"].get("frame_key"), ev["reading"]
    q = _run(ctx, d, "image_quality", frame_key=key)
    est = _run(ctx, d, "estimate_stage", cam=cam, frame_key=key)
    if est.get("ok"):
        g = _run(ctx, d, "get_gauge", hours=24)
        sat = saturation(_meta(ctx, cam), est, g)
        if sat:
            d["camera_status"] = "saturated"
            smax = est.get("stage_max_ft")
            why.append(f"gauge stale; {sat}: camera gives only a lower bound >= {smax} ft")
            return [action("MARK_PROVISIONAL", source="camera_lower_bound", stage_ft=smax, bound="lower"),
                    action("DENSIFY", minutes=15, hours=6)]
    if usable(q, ev) and est.get("ok") and est.get("in_calibrated_range"):
        why.append(f"gauge stale; camera gap-fill {est['stage_ft']} ± {est['sigma_ft']} ft marked provisional")
        return [action("MARK_PROVISIONAL", source="camera", stage_ft=est["stage_ft"], sigma_ft=est["sigma_ft"]),
                action("DENSIFY", minutes=15, hours=6)]
    why.append("gauge stale and camera not trustworthy now (" + (", ".join(q.get("issues", [])) or est.get("summary", "")) +
               "); holding the last known gauge value")
    return [action("MARK_PROVISIONAL", source="last_known", stage_ft=r.get("gauge_stage_ft"))]


def disagree(ctx, ev, d, why):
    cam, key = ev["cam_id"], ev["reading"].get("frame_key")
    g = _run(ctx, d, "get_gauge", hours=24)
    if fresh(g) and g.get("above_camera_range"):
        d["camera_status"] = "saturated"
        why.append(f"gauge {g['latest_ft']} ft is above the camera's calibrated range: camera saturated, not faulty; gauge trusted")
        return [action("NOOP", reason="camera_saturated", trust="gauge", gauge_ft=g["latest_ft"])]
    q = _run(ctx, d, "image_quality", frame_key=key)
    est = _run(ctx, d, "estimate_stage", cam=cam, frame_key=key)
    if not usable(q, ev) or not est.get("ok"):
        why.append("camera fault: " + (", ".join(q.get("issues", [])) or "frame does not register") + "; readings quarantined")
        return [action("QUARANTINE", reason="camera_fault")]
    if est.get("near_ceiling"):
        d["camera_status"] = "saturated"
        why.append(f"camera estimate {est['stage_ft']} ft is at its calibrated ceiling: saturated, not faulty; gauge trusted")
        return [action("NOOP", reason="camera_saturated", trust="gauge", gauge_ft=g.get("latest_ft"))]
    sig = max(est.get("sigma_ft") or 0.3, 0.1)
    if g.get("latest_ft") is None:
        why.append("no gauge data to disagree with")
        return [action("NOOP")]
    diff = est["stage_ft"] - g["latest_ft"]
    if abs(diff) <= 2 * sig:
        why.append(f"fresh camera estimate agrees with the gauge ({diff:+.2f} ft, σ {sig:.2f})")
        return [action("NOOP", reason="resolved")]
    jump = abs(g.get("max_step_ft") or 0) >= 0.3 and (g.get("step_isolation") or 0) >= 4
    stuck = (g.get("flat_hours") or 0) >= 6
    if jump or stuck:
        why.append(f"camera is usable and registered but differs by {diff:+.2f} ft; gauge "
                   + ("jumped in isolation" if jump else f"flat for {g['flat_hours']} h") + " -> gauge suspect, human review")
        return [action("OPEN_TICKET", kind="gauge_suspect", camera_ft=est["stage_ft"], gauge_ft=g["latest_ft"],
                       detail=g.get("summary"))]
    why.append(f"camera differs by {diff:+.2f} ft with a normal-looking gauge; trusting the gauge, camera quarantined")
    return [action("QUARANTINE", reason="disagree_gauge_normal")]


def rising(ctx, ev, d, why):
    cam, key, r = ev["cam_id"], ev["reading"].get("frame_key"), ev["reading"]
    meta = _meta(ctx, cam)
    out = [action("DENSIFY", minutes=15, hours=12)]
    g = _run(ctx, d, "get_gauge", hours=6)
    tide = g.get("tidal")
    if tide and tide.get("ok") and not tide.get("non_tidal_rise"):
        # D-0013 W2-1: on a tidal site a rise is the tide unless the water stands above the predicted tide
        why.append(f"tidal site: {g['latest_ft']} ft is the ordinary tide (predicted {tide['predicted_tide_ft']} ft, "
                   f"residual {tide['residual_ft']:+.2f} ft < {tide['surge_threshold_ft']:.2f}); no flood alert")
        if tide.get("king_tide") and tide_advisory_on():
            return [king_tide_advisory(tide, why)]
        return [action("NOOP", reason="tidal", residual_ft=tide["residual_ft"])]
    age = g.get("age_min")
    now_ft = g.get("latest_ft") if age is not None and age <= 60 else None      # age 0.0 is fresh, not missing
    if now_ft is None:
        est = _run(ctx, d, "estimate_stage", cam=cam, frame_key=key)
        now_ft = est.get("stage_ft")
    if now_ft is None:
        why.append("rise flagged but no current stage from gauge or camera; sampling densified")
        return out
    fc = _run(ctx, d, "get_nws_forecast")
    rate = (g.get("change_1h_ft") or 0.0)
    p50, p90 = meta.get("stage_p50", now_ft), meta.get("stage_p90", now_ft + 1)
    action_stage = ((fc.get("flood_categories_ft") or {}).get("action") if fc.get("available") else None)
    crest = fc.get("crest_ft") if fc.get("available") else round(now_ft + max(rate, 0) * 3, 2)
    alert = now_ft >= p90 or (action_stage is not None and crest is not None and crest >= action_stage) \
        or (rate >= 0.5 and now_ft >= p50) or bool(tide and tide.get("non_tidal_rise"))
    if not alert:
        why.append(f"rising ({rate:+.2f} ft/h) but {now_ft} ft is below the site p90 {p90}; sampling densified")
        return out
    o1 = _run(ctx, d, "render_wet_overlay", cam=cam, frame_key=key, stage_ft=now_ft, label="now")
    o2 = _run(ctx, d, "render_wet_overlay", cam=cam, frame_key=key, stage_ft=crest, label="crest") if crest else {}
    out.append(action("DRAFT_ALERT", stage_ft=now_ft, crest_ft=crest, crest_source="nws" if fc.get("available") else "trend_3h",
                      rate_ft_per_h=rate, overlay_now=o1.get("overlay_key"), overlay_crest=o2.get("overlay_key")))
    why.append(f"rising {rate:+.2f} ft/h at {now_ft} ft (site p90 {p90}); alert drafted for approval with overlays")
    if tide and tide.get("king_tide") and tide_advisory_on():   # surge on a king tide: the advisory adds tide context
        out.append(king_tide_advisory(tide, why))
    return out


def tide_advisory_on() -> bool:
    """RIVERSIGHT_TIDE_ADVISORY (default "0"): the v5 rules run caught 0/4 real king tides at Savannah and raised one
    advisory on an ordinary tide (results/agent_eval/V5_TIDE_RECAL.md), so it ships off until Cowork decides (Q-0014).
    The v5 evaluation ran with it on (RIVERSIGHT_TIDE_ADVISORY=1)."""
    import os
    return os.environ.get("RIVERSIGHT_TIDE_ADVISORY", "0") == "1"


def king_tide_advisory(tide: dict, why: list) -> dict:
    """D-0014: the *predicted* tide reaches the site's daily-max p99 -> low-severity advisory, approval needed."""
    why.append(f"predicted high tide {tide['predicted_high_24h_ft']} ft at {str(tide.get('predicted_high_time'))[:16]} UTC "
               f"reaches this site's daily-max p99 {tide.get('daily_max_p99_ft')} ft: king-tide advisory for approval")
    return action("TIDE_ADVISORY", severity="low", predicted_high_ft=tide["predicted_high_24h_ft"],
                  predicted_high_time=tide.get("predicted_high_time"), daily_max_p99_ft=tide.get("daily_max_p99_ft"),
                  text="Predicted high tide above this site's typical maximum; NWS may issue a coastal flood advisory.")


RECAL_FLAGS = {"DISAGREE", "OUT_OF_RANGE"}           # how drift / a flood that extended the range shows in readings


def recalibration(ctx, ev, d, why):
    """D-0014 W2-2: draft RECALIBRATE (approval needed) when W4's drift signal fires or a flood extended the
    calibrated range, and a refit bundle built on the served model exists. Evidence goes in the args."""
    rs = _run(ctx, d, "recal_status", cam=ev["cam_id"])
    if not rs.get("available") or not (rs.get("drifting") or rs.get("range_extended")):
        return []
    dr, m = rs.get("drift") or {}, rs.get("recal_meta") or {}
    why.append("camera residuals drift from the gauge" if rs.get("drifting") else "a flood extended the calibrated range")
    why.append(f"a refit bundle ({m.get('n_new_frames')} new frames) is ready: recalibration drafted for approval")
    return [action("RECALIBRATE", reason="drifting" if rs.get("drifting") else "range_extended",
                   median_residual_ft=dr.get("median_residual_ft"), sigma_ft=dr.get("sigma_ft"), n_drift=dr.get("n"),
                   n_new_frames=m.get("n_new_frames"), new_from=m.get("new_from"), new_to=m.get("new_to"),
                   stage_max_before_ft=m.get("stage_max_before_ft"), stage_max_after_ft=m.get("stage_max_after_ft"),
                   served_model_sha=rs.get("served_model_sha"), recal_model_sha=m.get("model_sha"))]


def low_quality(ctx, ev, d, why):
    if rising_now(ev):
        why.append("low image quality during a rise (turbid water, covered banks); frame kept, no lens ticket")
        return [action("NOOP", reason="rising_turbidity")]
    if persisted(ev, "LOW_QUALITY"):
        q = _run(ctx, d, "image_quality", frame_key=ev["reading"].get("frame_key"))
        if not q.get("usable"):
            why.append("frame quality poor for 3 cycles; lens check ticket")
            return [action("OPEN_TICKET", kind="lens_check", detail=q.get("summary"))]
    why.append("low-quality frame; the quality gate already suppresses it")
    return [action("NOOP")]


BEHAVIOURS = {"VIEW_CHANGE": view_change, "GAUGE_STALE": gauge_stale, "DISAGREE": disagree, "RISING": rising,
              "LOW_QUALITY": low_quality, "OUT_OF_RANGE": out_of_range}


def decide(event: dict[str, Any], ctx: tools.ToolContext) -> dict[str, Any]:
    d = schema.new_decision(event, "rules")
    flags = set(event.get("reading", {}).get("flags") or [])
    why, acts = [], []
    if "VIEW_CHANGE" in flags:                       # a moved camera invalidates every other camera-based check
        flags -= {"DISAGREE", "LOW_QUALITY"}
    if "OUT_OF_RANGE" in flags:                      # saturation explains the disagreement / bad gap-fill
        flags -= {"DISAGREE", "LOW_QUALITY", "GAUGE_STALE"}
    for f in schema.BEHAVIOUR_ORDER:
        if f in flags and f in BEHAVIOURS:
            acts += BEHAVIOURS[f](ctx, event, d, why)
    if RECAL_FLAGS & set(event.get("reading", {}).get("flags") or []) and "VIEW_CHANGE" not in flags:
        acts += recalibration(ctx, event, d, why)     # a moved camera needs re-anchoring, not a refit
    if not acts:
        why.append("no actionable flag")
    d["actions"] = acts
    d["rationale"] = "; ".join(w.rstrip(". ") for w in why) + "."
    return schema.finalize(event, d)


def handle(event: dict[str, Any], ctx: tools.ToolContext | None = None) -> dict[str, Any]:
    """Deterministic decision for one flagged reading (W1's fallback when Bedrock is unavailable)."""
    from riversight.agent import default_context
    ctx = ctx or default_context(event)
    ctx.event = event
    try:
        return decide(event, ctx)
    except Exception as e:                                                        # noqa: BLE001
        d = schema.new_decision(event, "rules")
        d["actions"] = [action("NOOP")]
        d["rationale"] = f"rules policy error ({type(e).__name__}: {e}); no action taken"
        return schema.finalize(event, d)
