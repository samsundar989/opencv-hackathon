"""Fleet agent (W2 owns this package; W1 committed only this stub).

Contract: docs/INTERFACES.md §3. ``handle(event) -> Decision`` is called by the
live cycle once per *flagged* reading. Until W2 lands the Bedrock loop, it
delegates to the deterministic rules policy.
"""
from __future__ import annotations

from typing import Any

from . import rules

Event = dict[str, Any]
Decision = dict[str, Any]


def handle(event: Event) -> Decision:
    """Decide what to do about one flagged reading (stub: rules policy)."""
    return rules.handle(event)


__all__ = ["Decision", "Event", "handle", "rules"]
