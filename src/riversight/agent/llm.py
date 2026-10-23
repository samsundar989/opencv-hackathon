"""River Steward LLM loop: plain Bedrock Converse tool use (boto3), no framework.

The model sees numbers and one-line summaries from the OpenCV tools, never images. It must finish by calling
`submit_decision`; `schema.finalize` then enforces the human-control rules whatever it asked for.

Budgets (SPRINT_W2): ≤ 8 tool calls per event, a daily token cap (`RIVERSIGHT_AGENT_DAILY_TOKENS`, default
2,000,000), and an estimated cost per decision. Temperature is not sent: Claude Haiku/Sonnet 5.5 reject
non-default sampling parameters, so reproducibility comes from repeated runs (eval arms run 3×), not from T=0.

Model ids are Bedrock cross-region inference profiles (Haiku/Sonnet 5.5 are not callable in-region in
us-east-2). Prices are estimates at Anthropic first-party list rates per MTok (Bedrock bills its own rates;
override with RIVERSIGHT_PRICE_<HAIKU|SONNET>_<IN|OUT>).
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Callable

from riversight.agent import schema, tools

HAIKU = os.environ.get("RIVERSIGHT_AGENT_MODEL", "us.anthropic.claude-haiku-5-5")
SONNET = os.environ.get("RIVERSIGHT_AGENT_SONNET", "us.anthropic.claude-sonnet-5-5")
REGION = os.environ.get("RIVERSIGHT_BEDROCK_REGION", "us-east-2")
MAX_TOOL_CALLS = 8
MAX_TURNS = 10
DAILY_TOKENS = int(os.environ.get("RIVERSIGHT_AGENT_DAILY_TOKENS", "2000000"))
PRICES = {"haiku": (0.10, 0.50), "sonnet": (2.00, 10.00)}       # USD per MTok in/out (estimate, see docstring)


def price(model: str) -> tuple[float, float]:
    fam = "sonnet" if "sonnet" in model else "haiku"
    pin, pout = PRICES[fam]
    return (float(os.environ.get(f"RIVERSIGHT_PRICE_{fam.upper()}_IN", pin)),
            float(os.environ.get(f"RIVERSIGHT_PRICE_{fam.upper()}_OUT", pout)))


SYSTEM = """You are River Steward, the operations agent for RiverSight: public USGS river webcams turned into \
camera water-level instruments, each calibrated against its own stream gauge. You are called once for each \
camera reading that the live cycle flagged. Decide what to do using the OpenCV tools, then call submit_decision.

What the flags mean
- VIEW_CHANGE: the frame failed to register to the camera's reference view.
- GAUGE_STALE: the USGS gauge has not reported recently; the camera may need to fill the gap.
- DISAGREE: the camera stage and the gauge stage differ by more than the camera's error band.
- RISING: the river is rising; flood state may change.
- LOW_QUALITY / NIGHT: image quality is poor / it is dark.

Actions (submit_decision.actions[].type)
- NOOP: nothing to do (for example a transient problem; the next frame is checked anyway).
- SET_REFERENCE {ref}: re-anchor the camera to a banked reference it now matches. Only for a calibrated banked view.
- QUARANTINE {reason}: exclude this camera's readings until cleared. Reversible.
- DENSIFY {minutes, hours}: sample this camera more often for a while.
- MARK_PROVISIONAL {source: camera|last_known, stage_ft, sigma_ft}: publish a provisional gap-fill value.
- OPEN_TICKET {kind: recalibration|gauge_suspect|lens_check, detail}: ask a human to look. Needs approval.
- DRAFT_ALERT {stage_ft, crest_ft, overlay_now, overlay_crest}: draft a flood alert for a human to approve.

Principles
- Base the decision on tool evidence, not on the flag alone. Flags are hints from cheap tests and are \
sometimes false alarms.
- Fog, rain on the lens, glare and night IR frames are transient: do not re-anchor or quarantine for them.
- A frame that still registers to its current reference needs no new reference.
- A camera with a new view that matches no calibrated reference cannot measure: quarantine it. Ask for \
recalibration only once the new view has persisted for several cycles (see the recent readings).
- When the gauge is stale, the camera can fill the gap only if the frame is usable and the estimate is \
within the calibrated range; otherwise hold the last known gauge value as provisional.
- When camera and gauge disagree: an unusable or unregistered camera frame is a camera fault. A usable, \
well-registered camera that disagrees with a gauge that jumped abruptly or has been stuck flat makes the \
gauge suspect (ticket for human review). Otherwise trust the gauge.
- When the river rises to a high stage for this site or rises fast, sample more often, render what will be \
under water now and at the expected crest, and draft an alert. Alerts and tickets always go to a human; never \
claim that one was sent.
- Use at most 8 tool calls. Call submit_decision exactly once, with a rationale of at most 3 sentences."""

SUBMIT = {"toolSpec": {"name": "submit_decision", "description": "Submit the final decision for this flagged reading.",
                       "inputSchema": {"json": {"type": "object", "required": ["actions", "rationale"], "properties": {
                           "actions": {"type": "array", "items": {"type": "object", "required": ["type"], "properties": {
                               "type": {"type": "string", "enum": list(schema.ACTION_TYPES)}, "args": {"type": "object"}}}},
                           "rationale": {"type": "string"}}}}}}


def event_prompt(event: dict) -> str:
    r = event.get("reading") or {}
    meta = event.get("site_meta") or {}
    keep = ("t_frame", "frame_key", "daylight", "registration", "quality", "camera_stage_ft", "camera_sigma_ft",
            "gauge_stage_ft", "gauge_time", "gauge_age_min", "flood_state", "flags")
    recent = [{"t": x.get("t_frame"), "flags": x.get("flags"), "camera_ft": x.get("camera_stage_ft"),
               "gauge_ft": x.get("gauge_stage_ft"), "registered": (x.get("registration") or {}).get("ok")}
              for x in (event.get("recent") or [])[-6:]]
    site = {k: meta.get(k) for k in ("cam_id", "nwis_id", "tier", "sigma_ft", "stage_p05", "stage_p50", "stage_p90",
                                     "stage_p95", "stage_min", "stage_max") if k in meta}
    return json.dumps({"cam_id": event.get("cam_id"), "reading": {k: r.get(k) for k in keep if k in r},
                       "site": site, "recent_readings_oldest_first": recent}, default=str)


class TokenLedger:
    """Daily token cap. Persists through the sink (S3 or local) so every Lambda/worker shares it."""

    def __init__(self, sink, cap: int | None = None):
        self.sink, self.cap = sink, DAILY_TOKENS if cap is None else cap

    def _key(self):
        return f"live/agent/usage/{time.strftime('%Y-%m-%d', time.gmtime())}.json"

    def used(self) -> int:
        if self.sink is None:
            return 0
        txt = self.sink.get_text(self._key())
        return int(json.loads(txt).get("tokens", 0)) if txt else 0

    def add(self, n: int, usd: float):
        if self.sink is None:
            return
        txt = self.sink.get_text(self._key())
        u = json.loads(txt) if txt else {"tokens": 0, "usd": 0.0, "decisions": 0}
        u["tokens"] += int(n)
        u["usd"] = round(u["usd"] + usd, 6)
        u["decisions"] += 1
        self.sink.put_json(self._key(), u)

    def exhausted(self) -> bool:
        return self.used() >= self.cap


_client = None


def bedrock_converse(**kw) -> dict:
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config
        _client = boto3.client("bedrock-runtime", region_name=REGION,
                               config=Config(retries={"max_attempts": 4, "mode": "adaptive"}, read_timeout=60))
    return _client.converse(**kw)


def _jsonable(x: Any) -> Any:
    return json.loads(json.dumps(x, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))


def run(event: dict, ctx: tools.ToolContext, model: str = HAIKU, converse: Callable[..., dict] | None = None,
        effort: str | None = os.environ.get("RIVERSIGHT_AGENT_EFFORT")) -> dict:
    """One LLM decision. Raises on transport errors (the caller falls back to rules)."""
    converse = converse or bedrock_converse
    d = schema.new_decision(event, "llm", model)
    msgs = [{"role": "user", "content": [{"text": event_prompt(event)}]}]
    tool_cfg = tools.bedrock_tool_config([SUBMIT])
    extra = {"output_config": {"effort": effort}} if effort else None
    n_tools, submitted = 0, None
    for turn in range(MAX_TURNS):
        kw = dict(modelId=model, system=[{"text": SYSTEM}], messages=msgs, toolConfig=tool_cfg,
                  inferenceConfig={"maxTokens": 4000})
        if extra:
            kw["additionalModelRequestFields"] = extra
        t0 = time.perf_counter()
        resp = converse(**kw)
        u = resp.get("usage") or {}
        d["tokens_in"] += int(u.get("inputTokens", 0))
        d["tokens_out"] += int(u.get("outputTokens", 0))
        d.setdefault("llm_ms", 0)
        d["llm_ms"] += round(1000 * (time.perf_counter() - t0))
        out = resp["output"]["message"]
        msgs.append(out)                                       # appended unchanged (keeps reasoning blocks valid)
        uses = [c["toolUse"] for c in out.get("content", []) if "toolUse" in c]
        if not uses:
            if resp.get("stopReason") == "end_turn" and submitted is None:
                msgs.append({"role": "user", "content": [{"text": "Call submit_decision now."}]})
                continue
            break
        results = []
        for tu in uses:
            if tu["name"] == "submit_decision":
                submitted = tu.get("input") or {}
                results.append({"toolResult": {"toolUseId": tu["toolUseId"], "content": [{"json": {"ok": True}}]}})
                continue
            n_tools += 1
            if n_tools > MAX_TOOL_CALLS:
                res = {"error": "tool budget exhausted", "summary": "tool budget (8) exhausted; call submit_decision now"}
            else:
                res, ms = tools.timed_call(ctx, tu["name"], tu.get("input") or {})
                d["steps"].append({"tool": tu["name"], "args": tu.get("input") or {}, "result_summary": res.get("summary", ""),
                                   "ms": ms})
            results.append({"toolResult": {"toolUseId": tu["toolUseId"], "content": [{"json": _jsonable(res)}],
                                           **({"status": "error"} if "error" in res else {})}})
        msgs.append({"role": "user", "content": results})
        if submitted is not None:
            break
    pin, pout = price(model)
    d["usd"] = round((d["tokens_in"] * pin + d["tokens_out"] * pout) / 1e6, 6)
    d["n_tool_calls"] = n_tools
    if submitted is None:
        raise RuntimeError(f"model did not submit a decision within {MAX_TURNS} turns")
    d["actions"] = [{"type": a.get("type"), "args": a.get("args") or {}} for a in submitted.get("actions") or []]
    d["rationale"] = submitted.get("rationale", "")
    return schema.finalize(event, d)
