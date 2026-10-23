"""Deterministic fallback policy (stub; W2 replaces the body).

Same signature as ``riversight.agent.handle``: Event -> Decision (INTERFACES §3).
"""
from __future__ import annotations

from typing import Any


def handle(event: dict[str, Any]) -> dict[str, Any]:
    """Return a NOOP decision for any event. W2 replaces this with the real policy."""
    return {
        "event_id": event.get("event_id"),
        "decided_by": "rules",
        "model": None,
        "tokens_in": 0,
        "tokens_out": 0,
        "usd": 0.0,
        "steps": [],
        "actions": [{"type": "NOOP", "args": {}, "needs_approval": False}],
        "rationale": "Stub policy: no action until W2's rules land.",
        "approval_id": None,
    }
