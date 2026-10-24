"""River Steward LLM loop: plain Bedrock Converse tool use (boto3), no framework.

The model sees numbers and one-line summaries from the OpenCV tools, never images. It must finish by calling
`submit_decision`; `schema.finalize` then enforces the human-control rules whatever it asked for.

Budgets (SPRINT_W2): ≤ 8 tool calls per event, a daily token cap (`RIVERSIGHT_AGENT_DAILY_TOKENS`, default
2,000,000), and an estimated cost per decision. Temperature is not sent (left at the model default), so
reproducibility comes from repeated runs (eval arms run 3×), not from T=0.

Models (ANSWER 0010): Claude 5.5 is blocked for this AWS account, so the agent runs on **Claude Haiku 4.5** and the
second-opinion / second-model arm on **Claude Sonnet 4.6**, with an optional **Claude Opus 4.5** arm — all through
Bedrock `us.` cross-region inference profiles in us-east-2. Prices are estimates at Anthropic first-party list rates
per MTok (Bedrock bills its own rates; override with RIVERSIGHT_PRICE_<KEY>_<IN|OUT>, KEY as in PRICES).
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable

from riversight.agent import schema, tools

HAIKU = os.environ.get("RIVERSIGHT_AGENT_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
SONNET = os.environ.get("RIVERSIGHT_AGENT_SONNET", "us.anthropic.claude-sonnet-4-6")
OPUS = os.environ.get("RIVERSIGHT_AGENT_OPUS", "us.anthropic.claude-opus-4-5-20251101-v1:0")
MODEL_NAMES = {"haiku-4-5": "Claude Haiku 4.5", "sonnet-4-6": "Claude Sonnet 4.6", "opus-4-5": "Claude Opus 4.5",
               "haiku-5-5": "Claude Haiku 5.5", "sonnet-5-5": "Claude Sonnet 5.5"}


def model_name(model_id: str | None) -> str | None:
    """Human-readable model name for reports and the dashboard (never a model that wasn't used)."""
    if not model_id:
        return None
    return next((v for k, v in MODEL_NAMES.items() if k in model_id), model_id)
REGION = os.environ.get("RIVERSIGHT_BEDROCK_REGION", "us-east-2")
MAX_TOOL_CALLS = 8
MAX_TURNS = 10
DAILY_TOKENS = int(os.environ.get("RIVERSIGHT_AGENT_DAILY_TOKENS", "2000000"))
# USD per MTok in/out at Anthropic first-party list prices (estimate, see docstring); most specific key first
PRICES = [("haiku-5-5", 0.10, 0.50), ("sonnet-5-5", 2.00, 10.00), ("haiku-4-5", 1.00, 5.00),
          ("sonnet-4", 3.00, 15.00), ("opus-4-5", 5.00, 25.00), ("haiku", 1.00, 5.00), ("sonnet", 3.00, 15.00),
          ("opus", 5.00, 25.00)]


def price(model: str) -> tuple[float, float]:
    key, pin, pout = next((p for p in PRICES if p[0] in model), PRICES[-1])
    env = key.upper().replace("-", "_")
    return (float(os.environ.get(f"RIVERSIGHT_PRICE_{env}_IN", pin)),
            float(os.environ.get(f"RIVERSIGHT_PRICE_{env}_OUT", pout)))


SYSTEM = """You are River Steward, the operations agent for RiverSight: public USGS river webcams turned into \
camera water-level instruments, each calibrated against its own stream gauge. You are called once for each \
camera reading that the live cycle flagged. Decide what to do using the OpenCV tools, then call submit_decision.

What the flags mean
- VIEW_CHANGE: the frame failed to register to the camera's reference view.
- GAUGE_STALE: the USGS gauge has not reported recently; the camera may need to fill the gap.
- DISAGREE: the camera stage and the gauge stage differ by more than the camera's error band.
- RISING: the river is rising; flood state may change.
- OUT_OF_RANGE: the river is above the highest stage this camera was calibrated on.
- LOW_QUALITY / NIGHT: image quality is poor / it is dark.

Actions (submit_decision.actions[].type)
- NOOP: nothing to do (for example a transient problem; the next frame is checked anyway).
- SET_REFERENCE {ref}: re-anchor the camera to a banked reference it now matches. Only for a calibrated banked view.
- QUARANTINE {reason}: exclude this camera's readings until cleared. Reversible.
- DENSIFY {minutes, hours}: sample this camera more often for a while.
- MARK_PROVISIONAL {source: camera|camera_lower_bound|last_known, stage_ft, sigma_ft}: publish a provisional \
gap-fill value; camera_lower_bound means "at least stage_ft".
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
- A camera cannot measure above its calibrated range: its estimate stalls near or below the calibrated \
maximum however high the water goes. That is saturation, not a fault. When the gauge is above the camera's \
range, or the camera estimate is at its ceiling, trust a fresh gauge and do not quarantine the camera; if the \
gauge is stale, publish only a lower bound (camera_lower_bound at the calibrated maximum), never a camera number.
- During a rise, muddy water and flooded banks lower contrast and texture; that alone is not a camera fault.
- On a tidal site (get_gauge reports a "tidal" block) the water rises and falls with the tide every day: never \
alert on the tide. Alert only on water above the predicted tide (non_tidal_rise: a surge or river flood).
- When the river rises to a high stage for this site or rises fast, sample more often, render what will be \
under water now and at the expected crest, and draft an alert. Alerts and tickets always go to a human; never \
claim that one was sent.
- Use at most 8 tool calls. Request tools that do not depend on each other in the same turn. Call \
submit_decision exactly once, with a rationale of at most 3 sentences."""

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
# The account's cross-region quota is 10 requests/min per model (service-quotas, Oct 23). Pace below it in-process
# and retry throttles with long backoff, so a throttle never silently turns an LLM decision into a rules fallback.
RPM = float(os.environ.get("RIVERSIGHT_BEDROCK_RPM", "9"))
THROTTLE_BACKOFF_S = (15, 30, 45, 60, 60, 60, 60, 60)
_pace_lock = threading.Lock()
_next_slot: dict[str, float] = {}


def _pace(model: str):
    with _pace_lock:
        now = time.monotonic()
        slot = max(now, _next_slot.get(model, 0.0))
        _next_slot[model] = slot + 60.0 / RPM
    if slot > now:
        time.sleep(slot - now)


def bedrock_converse(**kw) -> dict:
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config
        _client = boto3.client("bedrock-runtime", region_name=REGION,
                               config=Config(retries={"max_attempts": 2, "mode": "standard"}, read_timeout=90))
    from botocore.exceptions import ClientError
    for i in range(len(THROTTLE_BACKOFF_S) + 1):
        _pace(kw["modelId"])
        try:
            return _client.converse(**kw)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "ThrottlingException" or i == len(THROTTLE_BACKOFF_S):
                raise
            time.sleep(THROTTLE_BACKOFF_S[i])


def _jsonable(x: Any) -> Any:
    return json.loads(json.dumps(x, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))


def _maybe_json(x: Any) -> Any:
    if isinstance(x, str):
        try:
            return json.loads(x)
        except ValueError:
            return x
    return x


def parse_submission(sub: Any) -> dict:
    """Normalise submit_decision input. Models sometimes send actions as bare strings ("DENSIFY"), the whole
    input or args as a JSON string; 2 of the first 90 Haiku 4.5 runs did, and the strict parser raised (the
    decision then fell back to rules). Unknown shapes become no action; finalize() drops unknown types."""
    sub = _maybe_json(sub)
    if not isinstance(sub, dict):
        return {"actions": [], "rationale": str(sub)[:600]}
    acts = _maybe_json(sub.get("actions")) or []
    if isinstance(acts, (str, dict)):
        acts = [acts]
    out = []
    for a in acts:
        a = _maybe_json(a)
        if isinstance(a, str):
            out.append({"type": a, "args": {}})
        elif isinstance(a, dict):
            args = _maybe_json(a.get("args")) or {}
            out.append({"type": a.get("type"), "args": args if isinstance(args, dict) else {"value": args}})
    return {"actions": out, "rationale": str(sub.get("rationale") or "")}


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
        d["n_llm_calls"] = d.get("n_llm_calls", 0) + 1
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
    submitted = parse_submission(submitted)
    d["actions"] = submitted["actions"]
    d["rationale"] = submitted["rationale"]
    return schema.finalize(event, d)
