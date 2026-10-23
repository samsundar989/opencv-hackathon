"""Decision schema and guard rails shared by the LLM agent and the rules policy (INTERFACES §3).

Both policies return the same Decision dict. `finalize()` is the single choke point that enforces the
human-control rules no matter who decided:

  * DRAFT_ALERT and OPEN_TICKET always need approval (an approval id is minted for them);
  * only the seven known action types survive; anything else is dropped and noted;
  * NOOP is removed when a real action is present, and added when nothing is left.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

ACTION_TYPES = ("SET_REFERENCE", "QUARANTINE", "DENSIFY", "MARK_PROVISIONAL", "OPEN_TICKET", "DRAFT_ALERT", "NOOP")
NEEDS_APPROVAL = {"DRAFT_ALERT", "OPEN_TICKET"}
FLAGS = ("VIEW_CHANGE", "LOW_QUALITY", "GAUGE_STALE", "DISAGREE", "RISING", "OUT_OF_RANGE", "NIGHT")
# behaviour order when one reading carries several flags (most consequential first)
BEHAVIOUR_ORDER = ("RISING", "VIEW_CHANGE", "OUT_OF_RANGE", "DISAGREE", "GAUGE_STALE", "LOW_QUALITY", "NIGHT")

Event = dict[str, Any]
Decision = dict[str, Any]


def new_decision(event: Event, decided_by: str, model: str | None = None) -> Decision:
    return {"event_id": event.get("event_id"), "cam_id": event.get("cam_id"), "decided_by": decided_by,
            "model": model, "tokens_in": 0, "tokens_out": 0, "usd": 0.0, "steps": [], "actions": [],
            "rationale": "", "approval_id": None}


def action(type_: str, needs_approval: bool | None = None, **args) -> dict:
    return {"type": type_, "args": args, "needs_approval": type_ in NEEDS_APPROVAL if needs_approval is None
            else needs_approval}


def approval_id(event: Event, actions: list[dict]) -> str:
    h = hashlib.sha256(json.dumps([event.get("event_id"), [a["type"] for a in actions]]).encode()).hexdigest()
    return f"apr-{time.strftime('%Y%m%d', time.gmtime())}-{h[:10]}"


def finalize(event: Event, d: Decision) -> Decision:
    clean, dropped = [], []
    for a in d.get("actions") or []:
        t = str(a.get("type", "")).upper()
        if t not in ACTION_TYPES:
            dropped.append(t)
            continue
        clean.append({"type": t, "args": dict(a.get("args") or {}), "needs_approval": t in NEEDS_APPROVAL})
    real = [a for a in clean if a["type"] != "NOOP"]
    clean = real or [action("NOOP")]
    # one action per type (the first wins) so a looping model cannot open five tickets
    seen, uniq = set(), []
    for a in clean:
        if a["type"] not in seen:
            seen.add(a["type"])
            uniq.append(a)
    d["actions"] = uniq
    if dropped:
        d["rationale"] = (d.get("rationale") or "") + f" [dropped unknown actions: {', '.join(dropped)}]"
    if any(a["needs_approval"] for a in uniq):
        d["approval_id"] = d.get("approval_id") or approval_id(event, uniq)
    else:
        d["approval_id"] = None
    d["rationale"] = (d.get("rationale") or "").strip()[:600]
    return d


def action_types(d: Decision) -> list[str]:
    return [a["type"] for a in d.get("actions", [])]
