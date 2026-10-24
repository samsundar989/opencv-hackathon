"""Approval API behind CloudFront /api/* (INTERFACES §3 approval rule).

  GET  /api/approvals              pending + recent approvals (no secrets in them)
  POST /api/approvals/<id>         {"decision": "approve"|"reject", "token": "...", "note": "..."}

The token is never stored: the function holds only its sha256 (APPROVAL_TOKEN_SHA256), set at deploy time
by scripts/deploy.py, which sends the token itself to Samuel through the SNS alert topic.
"""
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone

import boto3

s3 = boto3.client("s3")
BUCKET = os.environ["BUCKET"]
PREFIX = "live/approvals/"


def _resp(code, body):
    return {"statusCode": code, "headers": {"content-type": "application/json", "cache-control": "no-store"},
            "body": json.dumps(body, default=str)}


def _list():
    out, tok = [], None
    while True:
        kw = {"Bucket": BUCKET, "Prefix": PREFIX, **({"ContinuationToken": tok} if tok else {})}
        r = s3.list_objects_v2(**kw)
        for o in r.get("Contents", []):
            out.append(json.loads(s3.get_object(Bucket=BUCKET, Key=o["Key"])["Body"].read()))
        if not r.get("IsTruncated"):
            break
        tok = r["NextContinuationToken"]
    out.sort(key=lambda a: a.get("created", ""), reverse=True)
    return out[:200]


def _from_cloudfront(event) -> bool:
    """Only CloudFront knows the origin secret; direct calls to the Function URL are refused."""
    want = os.environ.get("ORIGIN_SECRET_SHA256", "")
    got = (event.get("headers") or {}).get("x-origin-verify", "")
    return not want or hmac.compare_digest(want, hashlib.sha256(got.encode()).hexdigest())


def handler(event, context):
    if not _from_cloudfront(event):
        return _resp(403, {"error": "use the site"})
    if len(event.get("body") or "") > 4096:
        return _resp(413, {"error": "body too large"})
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "")
    parts = [p for p in path.split("/") if p]
    if parts[:2] != ["api", "approvals"]:
        return _resp(404, {"error": "not found"})
    if method == "GET":
        return _resp(200, {"approvals": _list()})
    if method != "POST" or len(parts) != 3:
        return _resp(405, {"error": "method not allowed"})
    aid = parts[2]
    if not aid.isalnum() or len(aid) > 64:
        return _resp(400, {"error": "bad id"})
    try:
        body = json.loads(event.get("body") or "{}")
    except ValueError:
        return _resp(400, {"error": "bad json"})
    want = os.environ.get("APPROVAL_TOKEN_SHA256", "")
    got = hashlib.sha256(str(body.get("token", "")).encode()).hexdigest()
    if not want or not hmac.compare_digest(want, got):
        return _resp(403, {"error": "bad token"})
    if body.get("decision") not in ("approve", "reject"):
        return _resp(400, {"error": "decision must be approve or reject"})
    key = f"{PREFIX}{aid}.json"
    try:
        item = json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    except s3.exceptions.NoSuchKey:
        return _resp(404, {"error": "no such approval"})
    if item.get("status") != "pending":
        return _resp(409, {"error": f"already {item.get('status')}"})
    item.update(status="approved" if body["decision"] == "approve" else "rejected",
                decided=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                note=str(body.get("note", ""))[:500])
    s3.put_object(Bucket=BUCKET, Key=key, Body=json.dumps(item).encode(), ContentType="application/json",
                  CacheControl="no-cache")
    day = item["decided"][:10]
    log_key = f"live/agent/approvals-{day}.jsonl"
    try:
        old = s3.get_object(Bucket=BUCKET, Key=log_key)["Body"].read()
    except s3.exceptions.NoSuchKey:
        old = b""
    s3.put_object(Bucket=BUCKET, Key=log_key, Body=old + (json.dumps(item) + "\n").encode(),
                  ContentType="application/x-ndjson", CacheControl="no-cache")
    return _resp(200, {"ok": True, "approval": item})
