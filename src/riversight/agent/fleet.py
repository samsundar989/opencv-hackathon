"""Fleet triage: several cameras flagged in the same cycle -> who needs a human first.

Input: the per-camera decisions of one cycle (from `agent.handle`). The rules ranking orders by the most
consequential action (alert > gauge suspect > recalibration / gap-fill > quarantine / re-anchor > densify >
nothing), breaking ties by how high the river is relative to the site. The LLM ranking gets the same decisions
(numbers and rationales, no images) and returns an order with one-line reasons through a `submit_ranking` tool.
"""
from __future__ import annotations

import json
import time

from riversight.agent import llm

ACTION_SEVERITY = {"DRAFT_ALERT": 5, "MARK_PROVISIONAL": 3, "QUARANTINE": 2, "SET_REFERENCE": 2, "DENSIFY": 1, "NOOP": 0}
TICKET_SEVERITY = {"gauge_suspect": 4, "recalibration": 3, "lens_check": 2}


def severity(decision: dict) -> int:
    s = 0
    for a in decision.get("actions", []):
        if a["type"] == "OPEN_TICKET":
            s = max(s, TICKET_SEVERITY.get((a.get("args") or {}).get("kind"), 3))
        else:
            s = max(s, ACTION_SEVERITY.get(a["type"], 0))
    return s


def _height(item: dict) -> float:
    r, m = item["event"].get("reading") or {}, item["event"].get("site_meta") or {}
    h = r.get("gauge_stage_ft") if r.get("gauge_stage_ft") is not None else r.get("camera_stage_ft")
    p50, p90 = m.get("stage_p50"), m.get("stage_p90")
    if h is None or p50 is None or p90 is None or p90 <= p50:
        return 0.0
    return (h - p50) / (p90 - p50)


def rank_rules(items: list[dict]) -> dict:
    order = sorted(items, key=lambda it: (-severity(it["decision"]), -_height(it)))
    return {"order": [it["key"] for it in order], "decided_by": "rules", "tokens_in": 0, "tokens_out": 0, "usd": 0.0}


SUBMIT = {"toolSpec": {"name": "submit_ranking", "description": "Submit the triage order, most urgent first.",
                       "inputSchema": {"json": {"type": "object", "required": ["order"], "properties": {
                           "order": {"type": "array", "items": {"type": "string"}},
                           "reasons": {"type": "object", "additionalProperties": {"type": "string"}}}}}}}

SYSTEM = """You are River Steward's fleet triage. Several river cameras were flagged in the same cycle and each \
already has a decision. One human operator will look at them in order. Rank the cameras by who needs the human \
first: an imminent flood alert awaiting approval outranks a suspect gauge, which outranks a camera that needs \
recalibration or a provisional gap-fill, which outranks a quarantined or re-anchored camera, which outranks \
anything already handled or harmless. Within a class, higher water relative to the site comes first. Call \
submit_ranking once with every key exactly once."""


def rank_llm(items: list[dict], model: str = llm.HAIKU, converse=None) -> dict:
    converse = converse or llm.bedrock_converse
    brief = [{"key": it["key"], "cam_id": it["event"].get("cam_id"),
              "flags": (it["event"].get("reading") or {}).get("flags"),
              "stage_ft": (it["event"].get("reading") or {}).get("gauge_stage_ft"),
              "site_p50_ft": (it["event"].get("site_meta") or {}).get("stage_p50"),
              "site_p90_ft": (it["event"].get("site_meta") or {}).get("stage_p90"),
              "actions": [{"type": a["type"], **({"kind": a["args"].get("kind")} if a["args"].get("kind") else {})}
                          for a in it["decision"].get("actions", [])],
              "rationale": it["decision"].get("rationale", "")[:300]} for it in items]
    msgs = [{"role": "user", "content": [{"text": json.dumps(brief)}]}]
    out = {"decided_by": "llm", "model": model, "tokens_in": 0, "tokens_out": 0}
    t0 = time.perf_counter()
    for _ in range(3):
        resp = converse(modelId=model, system=[{"text": SYSTEM}], messages=msgs, toolConfig={"tools": [SUBMIT]},
                        inferenceConfig={"maxTokens": 2000})
        u = resp.get("usage") or {}
        out["tokens_in"] += int(u.get("inputTokens", 0))
        out["tokens_out"] += int(u.get("outputTokens", 0))
        m = resp["output"]["message"]
        msgs.append(m)
        tu = next((c["toolUse"] for c in m.get("content", []) if "toolUse" in c), None)
        if tu:
            keys = [it["key"] for it in items]
            order = [k for k in (tu["input"].get("order") or []) if k in keys]
            order += [k for k in keys if k not in order]          # anything the model dropped goes last
            out.update(order=order, reasons=tu["input"].get("reasons") or {})
            break
        msgs.append({"role": "user", "content": [{"text": "Call submit_ranking now."}]})
    else:
        raise RuntimeError("no ranking submitted")
    pin, pout = llm.price(model)
    out["usd"] = round((out["tokens_in"] * pin + out["tokens_out"] * pout) / 1e6, 6)
    out["ms"] = round(1000 * (time.perf_counter() - t0))
    return out
