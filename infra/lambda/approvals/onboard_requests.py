"""POST /api/onboard_requests {"cam_id": "...", "note": "..."} — "Add a camera" (D-0013 W5-2; owner W5).

A request is stored as a **pending approval** (live/approvals/onb-<sha>.json, action ONBOARD_CAMERA), so it
appears on /approvals and needs the operator token like every other external action; nothing runs on a request
alone. The W5 poller on the compute box (scripts/onboard_requests.py) runs the onboarding pipeline only for
approved requests, validates the camera against the gauged-HIVIS catalogue, and mirrors status to
live/onboard_requests/. Uses only the bucket rights the approvals function already has (live/approvals/*).

Abuse limits: one request object per camera (idempotent: a repeat returns the existing status), camera ids are
[A-Za-z0-9_] only, notes are cut to 200 characters, and at most MAX_REQUESTS request objects can exist at once.
"""
import hashlib
import json
import re
import time

CAM_RE = re.compile(r"[A-Za-z0-9_]{3,120}")
MAX_REQUESTS = 100
KIND = "onboard_request"


def approval_id(cam_id: str) -> str:
    return "onb-" + hashlib.sha256(cam_id.encode()).hexdigest()[:16]


def iso_now(now: float) -> str:
    """Same format as the live cycle's approvals (sorted together by `created` in index._list; never mix types)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))


def request_item(cam_id: str, note: str, now: float) -> dict:
    return {"approval_id": approval_id(cam_id), "kind": KIND, "status": "pending", "created": iso_now(now), "cam_id": cam_id,
            "decided_by": "request",
            "actions": [{"type": "ONBOARD_CAMERA", "needs_approval": True,
                         "args": {"cam_id": cam_id, "pipeline": "scripts/onboard_site.py, frozen D-0007 setting",
                                  "cost": "see the Add-a-camera page (results/onboarding/cost.json)"}}],
            "rationale": ("Requested on the Add-a-camera page. Approving runs the onboarding pipeline once on the "
                          "RiverSight compute box; the camera is served only if forward-chaining CV reaches tier B."),
            "note": str(note or "")[:200]}


def _count(s3, bucket: str, prefix: str) -> int:
    n, tok = 0, None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix + "onb-", **({"ContinuationToken": tok} if tok else {})}
        r = s3.list_objects_v2(**kw)
        n += r.get("KeyCount", len(r.get("Contents", [])))
        if not r.get("IsTruncated"):
            return n
        tok = r["NextContinuationToken"]


def handle(s3, bucket: str, prefix: str, method: str, body_text: str | None) -> tuple[int, dict]:
    if method != "POST":
        return 405, {"error": "POST {cam_id} to request a camera; status is published at live/onboard_requests/index.json"}
    try:
        body = json.loads(body_text or "{}")
    except ValueError:
        return 400, {"error": "bad json"}
    cam = str(body.get("cam_id", "")).strip()
    if not CAM_RE.fullmatch(cam):
        return 400, {"error": "cam_id must be a NIMS camera id (letters, digits, underscores)"}
    key = f"{prefix}{approval_id(cam)}.json"
    try:
        old = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
        return 200, {"approval_id": old["approval_id"], "status": old.get("status"), "existing": True}
    except s3.exceptions.NoSuchKey:
        pass
    if _count(s3, bucket, prefix) >= MAX_REQUESTS:
        return 429, {"error": "the request queue is full; try again after the operator has cleared it"}
    item = request_item(cam, body.get("note", ""), time.time())
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(item).encode(), ContentType="application/json",
                  CacheControl="no-cache")
    return 201, {"approval_id": item["approval_id"], "status": "pending", "existing": False}
