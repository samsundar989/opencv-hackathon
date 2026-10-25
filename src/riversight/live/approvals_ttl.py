"""Approval TTL (D-0014 G2-2/3; deployed by W5 as D-0015 deploy owner).

Once per cycle, before the triage list is written:
  * a pending First Mallard DRAFT_ALERT created before the tidal fix (D-0013 W2-1, 2026-10-24 20:47 UTC) becomes
    `superseded` ("superseded by tidal logic"): the alert was an ordinary tide;
  * any other pending item older than TTL_H becomes `expired`;
  * "Add a camera" requests (kind onboard_request) never expire: they wait on an operator, not on a river.
Each change is written back to live/approvals/<id>.json and appended to live/agent/approvals-<day>.jsonl, the same
log the approvals API writes, so the record is kept; the triage panel lists only pending items.
"""
from __future__ import annotations

import pandas as pd

TTL_H = 24.0
TIDAL_FIX_UTC = pd.Timestamp("2026-10-24T20:47:31Z")        # commit 27681e9 (D-0013 W2-1)
TIDAL_SUPERSEDED = {"CA_First_Mallard_Branch_nr_Fairfield"}


def _created(item) -> pd.Timestamp | None:
    c = item.get("created")
    try:
        return pd.Timestamp(c, unit="s", tz="UTC") if isinstance(c, (int, float)) else pd.Timestamp(c).tz_convert("UTC")
    except (TypeError, ValueError):
        return None


def verdict(item: dict, now: pd.Timestamp) -> tuple[str, str] | None:
    """(new status, reason) for a pending item, or None to leave it pending."""
    if item.get("status") != "pending" or item.get("kind") == "onboard_request":
        return None
    t = _created(item)
    if t is None:
        return None
    types = {a.get("type") for a in item.get("actions") or []}
    if item.get("cam_id") in TIDAL_SUPERSEDED and "DRAFT_ALERT" in types and t < TIDAL_FIX_UTC:
        return "superseded", "superseded by tidal logic (D-0013 W2-1): this alert was an ordinary high tide"
    if (now - t).total_seconds() > TTL_H * 3600:
        return "expired", f"no decision within {TTL_H:.0f} h (D-0014 approval TTL); kept in the log"
    return None


def expire_approvals(store, now=None) -> int:
    now = pd.Timestamp(now or pd.Timestamp.now(tz="UTC"))
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    n = 0
    for key in store.list("live/approvals/"):
        if not key.endswith(".json"):
            continue
        item = store.get_json(key)
        v = verdict(item or {}, now) if item else None
        if v is None:
            continue
        item.update(status=v[0], decided=now.isoformat(timespec="seconds"), note=v[1], decided_by="ttl")
        store.put_json(key, item)
        store.append_jsonl(f"live/agent/approvals-{now:%Y-%m-%d}.jsonl", item)
        n += 1
    return n
