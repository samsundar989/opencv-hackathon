"""Where the live cycle writes (INTERFACES §2): a local directory (`--local`) or the S3 bucket (`--s3`).

Keys are the same in both, e.g. `live/sites/<cam>/latest.json`. S3 has no append, so `append_jsonl`
reads the day file, appends a line and writes it back (one writer per site per cycle, files stay small).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), default=str, allow_nan=False)


class LocalStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _p(self, key: str) -> Path:
        return self.root / key

    def get_bytes(self, key: str) -> bytes | None:
        p = self._p(key)
        return p.read_bytes() if p.exists() else None

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream", cache: str | None = None):
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)

    def get_json(self, key: str) -> Any:
        b = self.get_bytes(key)
        return None if b is None else json.loads(b)

    def put_json(self, key: str, obj: Any, cache: str | None = "no-cache"):
        self.put_bytes(key, _dumps(obj).encode(), "application/json", cache)

    def append_jsonl(self, key: str, obj: Any):
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(_dumps(obj) + "\n")

    def list(self, prefix: str) -> list[str]:
        base = self._p(prefix)
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.root)).replace("\\", "/") for p in base.rglob("*") if p.is_file())

    def url(self, key: str) -> str:
        return str(self._p(key))


class S3Store:
    def __init__(self, bucket: str, session=None):
        import boto3
        self.bucket = bucket
        self.s3 = (session or boto3).client("s3")

    def get_bytes(self, key: str) -> bytes | None:
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            return None

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream", cache: str | None = None):
        extra = {"ContentType": content_type}
        if cache:
            extra["CacheControl"] = cache
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)

    def get_json(self, key: str) -> Any:
        b = self.get_bytes(key)
        return None if b is None else json.loads(b)

    def put_json(self, key: str, obj: Any, cache: str | None = "no-cache"):
        self.put_bytes(key, _dumps(obj).encode(), "application/json", cache)

    def append_jsonl(self, key: str, obj: Any):
        old = self.get_bytes(key) or b""
        self.put_bytes(key, old + (_dumps(obj) + "\n").encode(), "application/x-ndjson", "no-cache")

    def list(self, prefix: str) -> list[str]:
        out, tok = [], None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": prefix, **({"ContinuationToken": tok} if tok else {})}
            r = self.s3.list_objects_v2(**kw)
            out += [o["Key"] for o in r.get("Contents", [])]
            if not r.get("IsTruncated"):
                return out
            tok = r["NextContinuationToken"]

    def url(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"
