"""Where the agent reads frames and writes decisions, approvals and overlays.

Frame keys (INTERFACES §2 `frame_key`) resolve in this order:
  synth:<fault>:<seed>:<base key>   a deterministic synthetic fault applied to the base frame (eval only;
                                    `faults.apply`). The agent never sees the fault name: tools get pixels.
  <live dir>/<key>                  W1's local live cycle mirrors the S3 layout on disk (RIVERSIGHT_LIVE_DIR,
                                    default <repo>/live_local, the same default as `live.cycle --local`)
  <repo>/<key> or an absolute path  cached history frames (data/raw/720/...)
  s3://<RIVERSIGHT_BUCKET>/<key>    the deployed live cycle

The sink mirrors the same key layout: the live dir, or S3 when RIVERSIGHT_BUCKET is set. In the live cycle W1
writes the decision log and approval items itself (`live.cycle.apply_decision`); the agent's sink holds the
kill switch, the token ledger and the overlays it renders. Kill switch: the object `live/agent/ENABLED` containing "false" (or the env var
RIVERSIGHT_AGENT_ENABLED=false) turns every decision into a logged NOOP.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
KILL_KEY = "live/agent/ENABLED"


def live_dir() -> Path:
    """W1's local live store (`python -m riversight.live.cycle --local` defaults to <repo>/live_local)."""
    return Path(os.environ.get("RIVERSIGHT_LIVE_DIR", ROOT / "live_local"))


def _bucket() -> str | None:
    return os.environ.get("RIVERSIGHT_BUCKET") or None


_s3 = None


def s3():
    global _s3
    if _s3 is None:
        import boto3
        _s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-2"))
    return _s3


def _decode(buf: bytes) -> np.ndarray | None:
    return cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR)


_cache: dict[str, np.ndarray] = {}


def load_frame(key: str) -> np.ndarray | None:
    """Frame key → BGR uint8 image, or None if it cannot be found/decoded."""
    if not key:
        return None
    if key in _cache:
        return _cache[key]
    img = None
    if key.startswith("synth:"):
        from riversight.agent import faults
        _, fault, seed, base = key.split(":", 3)
        b = load_frame(base)
        img = None if b is None else faults.apply(b, fault, int(seed))
    else:
        for p in (live_dir() / key, Path(key), ROOT / key):
            if p.exists():
                img = cv2.imread(str(p))
                break
        if img is None and _bucket():
            try:
                img = _decode(s3().get_object(Bucket=_bucket(), Key=key)["Body"].read())
            except Exception:                                                     # noqa: BLE001
                img = None
    if img is not None:
        if len(_cache) > 64:
            _cache.clear()
        _cache[key] = img
    return img


class Sink:
    """Decision log, approval items and overlay images, under the INTERFACES §3 key layout."""

    def __init__(self, local_dir: Path | None = None, bucket: str | None = None):
        self.bucket = bucket if bucket is not None else _bucket()
        self.dir = Path(local_dir) if local_dir else live_dir()

    # -- primitives
    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        if self.bucket:
            s3().put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        else:
            p = self.dir / key
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        return key

    def get_text(self, key: str) -> str | None:
        if self.bucket:
            try:
                return s3().get_object(Bucket=self.bucket, Key=key)["Body"].read().decode("utf-8")
            except Exception:                                                     # noqa: BLE001
                return None
        p = self.dir / key
        return p.read_text(encoding="utf-8") if p.exists() else None

    def put_json(self, key: str, obj: Any) -> str:
        return self.put_bytes(key, json.dumps(obj, indent=1, default=str).encode(), "application/json")

    def append_jsonl(self, key: str, obj: Any) -> str:
        line = json.dumps(obj, default=str) + "\n"
        if self.bucket:          # S3 has no append; decisions are rare (flagged readings only), so RMW is fine
            old = self.get_text(key) or ""
            return self.put_bytes(key, (old + line).encode(), "application/x-ndjson")
        p = self.dir / key
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line)
        return key

    def put_jpeg(self, key: str, img: np.ndarray, quality: int = 85) -> str:
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return self.put_bytes(key, buf.tobytes(), "image/jpeg") if ok else ""

    # -- agent-level
    def enabled(self) -> bool:
        if os.environ.get("RIVERSIGHT_AGENT_ENABLED", "").lower() == "false":
            return False
        txt = self.get_text(KILL_KEY)
        return not (txt is not None and txt.strip().lower() == "false")

    def log_decision(self, decision: dict) -> str:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        return self.append_jsonl(f"live/agent/{day}.jsonl", decision)

    def write_approval(self, event: dict, decision: dict) -> str:
        item = {"approval_id": decision["approval_id"], "status": "pending", "created": time.time(),
                "cam_id": event.get("cam_id"), "event_id": event.get("event_id"),
                "actions": [a for a in decision["actions"] if a["needs_approval"]],
                "rationale": decision.get("rationale"), "reading": {k: event.get("reading", {}).get(k) for k in
                ("t_frame", "camera_stage_ft", "camera_sigma_ft", "gauge_stage_ft", "flood_state", "flags", "overlay_key")}}
        return self.put_json(f"live/approvals/{decision['approval_id']}.json", item)
