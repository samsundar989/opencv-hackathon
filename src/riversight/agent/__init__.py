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


def second_opinion(event: Event, ctx: ToolContext, d: Decision, converse=None) -> Decision:
    """Sonnet 5.5 re-decides an event whose Haiku decision would page a human (RIVERSIGHT_AGENT_ESCALATE=1).
    The Haiku decision stands; disagreement is recorded so the approver sees it."""
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
           use_llm: bool | None = None, record: bool | None = None, write_log: bool = False) -> Decision:
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
    if record:
        ledger.add(d.get("tokens_in", 0) + d.get("tokens_out", 0), d.get("usd", 0.0))
    if write_log:
        if d.get("approval_id"):
            sink.write_approval(event, d)
        sink.log_decision(d)
    return d


__all__ = ["Decision", "Event", "ToolContext", "default_context", "handle", "rules"]
