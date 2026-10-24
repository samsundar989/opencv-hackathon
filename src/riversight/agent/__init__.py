"""River Steward — the RiverSight fleet agent (W2). Contract: docs/INTERFACES.md §3–4.

``handle(event) -> Decision`` is called by the live cycle once per *flagged* reading:

  kill switch (live/agent/ENABLED=false)  -> logged NOOP, decided_by "kill_switch"
  daily token cap reached                 -> rules policy
  Bedrock Converse agent (Haiku 5.5)      -> on any transport/model error, rules policy
  schema.finalize                         -> approval rule enforced whoever decided
  audit log + pending approval items      -> live/agent/YYYY-MM-DD.jsonl, live/approvals/<id>.json

``rules.handle(event)`` is the deterministic fallback with the same signature.
"""
from __future__ import annotations

import json
import os
from typing import Any

import pandas as pd

from riversight.agent import rules, schema
from riversight.agent.schema import Decision, Event
from riversight.agent.store import Sink
from riversight.agent.tools import ToolContext


def default_context(event: Event, sink: Sink | None = None, evidence: str = "full") -> ToolContext:
    mode = event.get("mode", "live")
    now = None
    if mode != "live":
        t = (event.get("reading") or {}).get("t_frame")
        now = pd.Timestamp(t) if t else None
    return ToolContext(mode=mode, evidence=evidence, sink=sink or Sink(), now=now, event=event)


def _kill_decision(event: Event) -> Decision:
    d = schema.new_decision(event, "kill_switch")
    d["actions"] = [schema.action("NOOP")]
    d["rationale"] = "Agent disabled by the kill switch (live/agent/ENABLED=false); no action taken."
    return schema.finalize(event, d)


ALERT_HOLD_H, ALERT_STEP_FT = 12.0, 0.5


def alert_hysteresis(event: Event, d: Decision, sink: Sink) -> Decision:
    """One drafted alert per site per rise: a new DRAFT_ALERT within ALERT_HOLD_H of the last one is suppressed
    unless the stage or crest is ALERT_STEP_FT higher. Without this the agent drafts an alert (and the live cycle
    emails the approver) every cycle the river stays high — 40 drafts in the Hancock Jul 29 replay."""
    alert = next((a for a in d["actions"] if a["type"] == "DRAFT_ALERT"), None)
    if alert is None:
        return d
    key = f"live/agent/alerts/{event.get('cam_id')}.json"
    t = pd.Timestamp((event.get("reading") or {}).get("t_frame") or pd.Timestamp.now(tz="UTC"))
    level = max(v for v in (alert["args"].get("stage_ft"), alert["args"].get("crest_ft"), -1e9) if v is not None)
    txt = sink.get_text(key)
    last = json.loads(txt) if txt else None
    if last and (t - pd.Timestamp(last["t"])).total_seconds() < ALERT_HOLD_H * 3600 and level < last["level"] + ALERT_STEP_FT:
        d["actions"] = [a for a in d["actions"] if a["type"] != "DRAFT_ALERT"]
        d["suppressed_alert"] = {"previous": last, "level_ft": level}
        d["rationale"] += f" [alert already drafted {last['t']} at {last['level']:.2f} ft; duplicate suppressed]"
        return schema.finalize(event, d)
    sink.put_json(key, {"t": t.isoformat(), "level": level, "approval_id": d.get("approval_id")})
    return d


TICKET_HOLD_H = 24.0


def ticket_hysteresis(event: Event, d: Decision, sink: Sink) -> Decision:
    """One open ticket per site and kind per TICKET_HOLD_H. A camera that stays moved / out of range would
    otherwise get a new recalibration ticket (and an approval email) every cycle — 13 for Animas on Oct 23
    between 21:32 and 00:47 UTC."""
    tickets = [a for a in d["actions"] if a["type"] == "OPEN_TICKET"]
    if not tickets:
        return d
    t = pd.Timestamp((event.get("reading") or {}).get("t_frame") or pd.Timestamp.now(tz="UTC"))
    keep, dropped = [], []
    for a in tickets:
        kind = (a.get("args") or {}).get("kind") or "other"
        key = f"live/agent/tickets/{event.get('cam_id')}__{kind}.json"
        txt = sink.get_text(key)
        last = json.loads(txt) if txt else None
        if last and (t - pd.Timestamp(last["t"])).total_seconds() < TICKET_HOLD_H * 3600:
            dropped.append(f"{kind} (open since {last['t']})")
        else:
            sink.put_json(key, {"t": t.isoformat(), "kind": kind})
            keep.append(a)
    if dropped:
        d["actions"] = [a for a in d["actions"] if a["type"] != "OPEN_TICKET"] + keep
        d["suppressed_tickets"] = dropped
        d["rationale"] += f" [ticket already open: {', '.join(dropped)}; duplicate suppressed]"
        d = schema.finalize(event, d)
    return d


def drift_review(event: Event, ctx: ToolContext, d: Decision, converse=None) -> Decision:
    """Hybrid gauge-drift review: the rules quarantined a usable, registered camera because it disagrees with a
    normal-looking gauge — the one case the rules cannot judge (a slowly drifting gauge looks normal). Sonnet 4.6
    re-decides with the same tools; if it judges the gauge suspect, the quarantine becomes a human-approved
    OPEN_TICKET gauge_suspect (nothing external happens without approval). Otherwise the rules decision stands."""
    from riversight.agent import llm
    try:
        s = llm.run(event, ctx, model=llm.SONNET, converse=converse)
    except Exception as e:                                                        # noqa: BLE001
        d["drift_review"] = {"error": type(e).__name__}
        return d
    d["tokens_in"] += s["tokens_in"]
    d["tokens_out"] += s["tokens_out"]
    d["usd"] = round(d["usd"] + s["usd"], 6)
    ticket = next((a for a in s["actions"] if a["type"] == "OPEN_TICKET" and (a.get("args") or {}).get("kind") == "gauge_suspect"), None)
    d["drift_review"] = {"model": s["model"], "actions": schema.action_types(s), "gauge_suspect": ticket is not None,
                         "rationale": s["rationale"]}
    if ticket is None:
        return d
    d["actions"] = [a for a in d["actions"] if a["type"] != "QUARANTINE"] + [ticket]
    d["decided_by"] = "rules+llm_review"
    d["rationale"] += f" [Sonnet drift review: gauge suspect, ticket instead of quarantine: {s['rationale'][:200]}]"
    return schema.finalize(event, d)


def second_opinion(event: Event, ctx: ToolContext, d: Decision, converse=None) -> Decision:
    """Sonnet 4.6 re-decides an event whose decision (Haiku 4.5, or the rules in rules_first mode) would page a
    human (RIVERSIGHT_AGENT_ESCALATE=1). The first decision stands; disagreement is recorded for the approver."""
    from riversight.agent import llm
    try:
        s = llm.run(event, ctx, model=llm.SONNET, converse=converse)
    except Exception as e:                                                        # noqa: BLE001
        d["second_opinion"] = {"error": f"{type(e).__name__}"}
        return d
    mine = {a["type"] for a in d["actions"] if a["needs_approval"]}
    theirs = {a["type"] for a in s["actions"] if a["needs_approval"]}
    d["second_opinion"] = {"model": s["model"], "actions": schema.action_types(s), "agrees": mine == theirs,
                           "rationale": s["rationale"]}
    d["tokens_in"] += s["tokens_in"]
    d["tokens_out"] += s["tokens_out"]
    d["usd"] = round(d["usd"] + s["usd"], 6)
    if mine != theirs:
        d["rationale"] += f" [Sonnet second opinion disagrees: {', '.join(sorted(theirs)) or 'no approval needed'}]"
    return d


def handle(event: Event, ctx: ToolContext | None = None, model: str | None = None, converse=None,
           use_llm: bool | None = None, record: bool | None = None, write_log: bool = False,
           agent_mode: str | None = None, escalate: bool | None = None) -> Decision:
    """Decide what to do about one flagged reading.

    record     honour the kill switch and charge the daily token ledger (default: live mode only)
    write_log  also append the decision log and pending approval items; off by default because the live
               cycle (W1 `apply_decision`) writes those itself — the replay script turns it on."""
    from riversight.agent import llm
    ctx = ctx or default_context(event)
    ctx.event = event
    sink = ctx.sink or Sink()
    record = (event.get("mode", "live") == "live") if record is None else record
    use_llm = (os.environ.get("RIVERSIGHT_AGENT_LLM", "1") != "0") if use_llm is None else use_llm
    ledger = llm.TokenLedger(sink if record else None)
    if record and not sink.enabled():
        d = _kill_decision(event)
    elif not use_llm:
        d = rules.handle(event, ctx)
    elif (agent_mode or os.environ.get("RIVERSIGHT_AGENT_MODE", "llm_first")) == "rules_first":
        # ANSWER 0011 / D-0012 hybrid: the deterministic OpenCV-evidence policy acts (93.9 % in the frozen eval vs
        # 71.4 % Sonnet 4.6 / 58.8 % Haiku 4.5); Claude Sonnet 4.6 reviews gauge drift (where the rules are blind)
        # and gives a recorded second opinion on anything that would page a human, within the token cap.
        d = rules.handle(event, ctx)
        capped = record and ledger.exhausted()
        if not capped and any((a.get("args") or {}).get("reason") == "disagree_gauge_normal" for a in d["actions"]):
            d = drift_review(event, ctx, d, converse)
        esc = (os.environ.get("RIVERSIGHT_AGENT_ESCALATE") == "1") if escalate is None else escalate
        if d.get("approval_id") and esc and not capped:
            d = second_opinion(event, ctx, d, converse)
    elif record and ledger.exhausted():
        d = rules.handle(event, ctx)
        d["rationale"] += f" [daily token cap {ledger.cap} reached: rules policy]"
        d["fallback_reason"] = "token_cap"
    else:
        try:
            d = llm.run(event, ctx, model=model or llm.HAIKU, converse=converse)
            if d.get("approval_id") and os.environ.get("RIVERSIGHT_AGENT_ESCALATE") == "1" and (model or llm.HAIKU) != llm.SONNET:
                d = second_opinion(event, ctx, d, converse)
        except Exception as e:                                                    # noqa: BLE001
            d = rules.handle(event, ctx)
            d["rationale"] += f" [LLM unavailable ({type(e).__name__}): rules policy]"
            d["fallback_reason"] = f"{type(e).__name__}: {str(e)[:200]}"
    if event.get("mode", "live") != "eval":           # eval episodes are independent; live/replay keep state
        d = alert_hysteresis(event, d, sink)
        d = ticket_hysteresis(event, d, sink)
    if record:
        ledger.add(d.get("tokens_in", 0) + d.get("tokens_out", 0), d.get("usd", 0.0))
    if write_log:
        if d.get("approval_id"):
            sink.write_approval(event, d)
        sink.log_decision(d)
    return d


__all__ = ["Decision", "Event", "ToolContext", "default_context", "handle", "rules"]
