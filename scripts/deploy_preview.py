"""Preview the dashboard locally with the same layout CloudFront serves.

  python -m riversight.live.cycle --local        # fill live_local/live/
  python scripts/deploy_preview.py               # http://localhost:8765/

/        → web/ + the generated site data (scripts/deploy.site_data)
/live/*  → live_local/live/*
/api/approvals → approvals read from live_local (read-only; POST answers 501)
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from deploy import site_data  # noqa: E402

LIVE = ROOT / "live_local"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    data = site_data()

    class H(BaseHTTPRequestHandler):
        def _send(self, code, body: bytes, ct="application/octet-stream"):
            self.send_response(code)
            self.send_header("content-type", ct)
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path.lstrip("/") or "index.html"
            if path == "api/approvals":
                items = [json.loads(p.read_text(encoding="utf-8")) for p in (LIVE / "live" / "approvals").glob("*.json")]
                return self._send(200, json.dumps({"approvals": items}).encode(), "application/json")
            if path.startswith("live/"):
                p = LIVE / path
            elif path in data:
                return self._send(200, data[path], mimetypes.guess_type(path)[0] or "application/json")
            else:
                p = ROOT / "web" / path
            if p.is_file():
                return self._send(200, p.read_bytes(), mimetypes.guess_type(str(p))[0] or "application/octet-stream")
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            self._send(501, b'{"error":"preview is read-only"}', "application/json")

        def log_message(self, *args):
            pass

    print(f"http://localhost:{a.port}/", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
