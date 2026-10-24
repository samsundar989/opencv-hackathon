"""W5 'Add a camera' (D-0013): the Lambda route queues a pending approval and never runs anything itself."""
import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
LAMBDA = ROOT / "infra" / "lambda" / "approvals"


class NoSuchKey(Exception):
    pass


class FakeS3:
    def __init__(self):
        self.objs = {}
        self.exceptions = type("E", (), {"NoSuchKey": NoSuchKey})

    def get_object(self, Bucket, Key):
        if Key not in self.objs:
            raise NoSuchKey(Key)
        return {"Body": mock.Mock(read=lambda: self.objs[Key])}

    def put_object(self, Bucket, Key, Body, **kw):
        self.objs[Key] = Body

    def list_objects_v2(self, Bucket, Prefix, **kw):
        ks = [k for k in self.objs if k.startswith(Prefix)]
        return {"Contents": [{"Key": k} for k in ks], "KeyCount": len(ks), "IsTruncated": False}


def _mod():
    sys.path.insert(0, str(LAMBDA))
    import onboard_requests
    return onboard_requests


def test_request_is_a_pending_approval_and_idempotent():
    m, s3 = _mod(), FakeS3()
    code, out = m.handle(s3, "b", "live/approvals/", "POST", json.dumps({"cam_id": "TX_Some_Creek_at_Somewhere", "note": "x" * 500}))
    assert code == 201 and out["status"] == "pending"
    item = json.loads(s3.objs[f"live/approvals/{out['approval_id']}.json"])
    assert item["actions"][0]["type"] == "ONBOARD_CAMERA" and item["actions"][0]["needs_approval"]
    assert len(item["note"]) == 200 and item["status"] == "pending"
    assert isinstance(item["created"], str) and item["created"].endswith("Z")   # sorts with the cycle's ISO approvals
    code2, out2 = m.handle(s3, "b", "live/approvals/", "POST", json.dumps({"cam_id": "TX_Some_Creek_at_Somewhere"}))
    assert code2 == 200 and out2["existing"] and len(s3.objs) == 1


def test_bad_input_and_queue_cap():
    m, s3 = _mod(), FakeS3()
    for bad in ("", "../etc", "a/b", "x y", "ab"):
        assert m.handle(s3, "b", "live/approvals/", "POST", json.dumps({"cam_id": bad}))[0] == 400
    assert m.handle(s3, "b", "live/approvals/", "GET", None)[0] == 405
    assert m.handle(s3, "b", "live/approvals/", "POST", "{nope")[0] == 400
    for i in range(m.MAX_REQUESTS):
        s3.objs[f"live/approvals/onb-{i:016d}.json"] = b"{}"
    assert m.handle(s3, "b", "live/approvals/", "POST", json.dumps({"cam_id": "NY_New_Cam"}))[0] == 429


def test_routed_by_the_approvals_handler():
    sys.path.insert(0, str(LAMBDA))
    spec = importlib.util.spec_from_file_location("approvals_index_w5", LAMBDA / "index.py")
    idx = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"boto3": mock.MagicMock()}), mock.patch.dict(os.environ, {"BUCKET": "b"}):
        spec.loader.exec_module(idx)
    idx.s3 = FakeS3()
    ev = {"requestContext": {"http": {"method": "POST"}}, "rawPath": "/api/onboard_requests",
          "body": json.dumps({"cam_id": "OH_Some_River_at_Town"}), "headers": {}}
    with mock.patch.dict(os.environ, {"ORIGIN_SECRET_SHA256": ""}):
        r = idx.handler(ev, None)
    assert r["statusCode"] == 201
    assert any(k.startswith("live/approvals/onb-") for k in idx.s3.objs)
