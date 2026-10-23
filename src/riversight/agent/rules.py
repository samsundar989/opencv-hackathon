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
    if q.get("usable") and est.get("ok") and est.get("in_calibrated_range"):
        why.append(f"gauge stale; camera gap-fill {est['stage_ft']} ± {est['sigma_ft']} ft marked provisional")
        return [action("MARK_PROVISIONAL", source="camera", stage_ft=est["stage_ft"], sigma_ft=est["sigma_ft"]),
                action("DENSIFY", minutes=15, hours=6)]
    why.append("gauge stale and camera not trustworthy now (" + (", ".join(q.get("issues", [])) or est.get("summary", "")) +
               "); holding the last known gauge value")
    return [action("MARK_PROVISIONAL", source="last_known", stage_ft=r.get("gauge_stage_ft"))]


def disagree(ctx, ev, d, why):
    cam, key = ev["cam_id"], ev["reading"].get("frame_key")
    q = _run(ctx, d, "image_quality", frame_key=key)
    est = _run(ctx, d, "estimate_stage", cam=cam, frame_key=key)
    if not q.get("usable") or not est.get("ok"):
        why.append("camera fault: " + (", ".join(q.get("issues", [])) or "frame does not register") + "; readings quarantined")
        return [action("QUARANTINE", reason="camera_fault")]
    g = _run(ctx, d, "get_gauge", hours=24)
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
        or (rate >= 0.5 and now_ft >= p50)
    if not alert:
        why.append(f"rising ({rate:+.2f} ft/h) but {now_ft} ft is below the site p90 {p90}; sampling densified")
        return out
    o1 = _run(ctx, d, "render_wet_overlay", cam=cam, frame_key=key, stage_ft=now_ft, label="now")
    o2 = _run(ctx, d, "render_wet_overlay", cam=cam, frame_key=key, stage_ft=crest, label="crest") if crest else {}
    out.append(action("DRAFT_ALERT", stage_ft=now_ft, crest_ft=crest, crest_source="nws" if fc.get("available") else "trend_3h",
                      rate_ft_per_h=rate, overlay_now=o1.get("overlay_key"), overlay_crest=o2.get("overlay_key")))
    why.append(f"rising {rate:+.2f} ft/h at {now_ft} ft (site p90 {p90}); alert drafted for approval with overlays")
    return out


def low_quality(ctx, ev, d, why):
    if persisted(ev, "LOW_QUALITY"):
        q = _run(ctx, d, "image_quality", frame_key=ev["reading"].get("frame_key"))
        if not q.get("usable"):
            why.append("frame quality poor for 3 cycles; lens check ticket")
            return [action("OPEN_TICKET", kind="lens_check", detail=q.get("summary"))]
    why.append("low-quality frame; the quality gate already suppresses it")
    return [action("NOOP")]


BEHAVIOURS = {"VIEW_CHANGE": view_change, "GAUGE_STALE": gauge_stale, "DISAGREE": disagree, "RISING": rising,
              "LOW_QUALITY": low_quality}


def decide(event: dict[str, Any], ctx: tools.ToolContext) -> dict[str, Any]:
    d = schema.new_decision(event, "rules")
    flags = set(event.get("reading", {}).get("flags") or [])
    why, acts = [], []
    if "VIEW_CHANGE" in flags:                       # a moved camera invalidates every other camera-based check
        flags -= {"DISAGREE", "LOW_QUALITY"}
    for f in schema.BEHAVIOUR_ORDER:
        if f in flags and f in BEHAVIOURS:
            acts += BEHAVIOURS[f](ctx, event, d, why)
    if not acts:
        why.append("no actionable flag")
    d["actions"] = acts
    d["rationale"] = " ".join(why)
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
