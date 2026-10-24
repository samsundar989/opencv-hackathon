"""W1: approvals Lambda accepts the agent's hyphenated approval ids and still rejects path tricks."""
import importlib.util
import os
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("approvals_index", ROOT / "infra" / "lambda" / "approvals" / "index.py")
    m = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"boto3": mock.MagicMock()}), mock.patch.dict(os.environ, {"BUCKET": "test-bucket"}):
        spec.loader.exec_module(m)
    return m


def test_valid_id():
    m = _load()
    assert m.valid_id("apr-20261023-1a09d4dc90")        # W2 agent ids (regression: was rejected as "bad id")
    assert m.valid_id("3f2a9c1d0e4b")                   # cycle ids
    for bad in ("", "../x", "a/b", "a.b", "x" * 65, "apr 1"):
        assert not m.valid_id(bad)
