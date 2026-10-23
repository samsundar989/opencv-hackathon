"""Check the frozen-protocol hashes in results/constants.sha256 (D-0007).

For every hashed file: does the working copy still match, and does the version committed with the hash
file match? A file edited after the freeze (for example, the live pipeline improving the registrar) shows
as "changed since freeze"; the kill-test numbers were produced by the frozen version, which is still
checked against its hash through git history.

    python report/verify_frozen.py          exit 1 only if a frozen version does not match its hash
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HASHES = ROOT / "results" / "constants.sha256"


def sha(b: bytes) -> str:
    return hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()   # same normalisation as freeze_config.py


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def main() -> None:
    freeze = git("log", "-1", "--format=%h", "--", str(HASHES.relative_to(ROOT))).decode().strip()
    print(f"hash file last committed in {freeze}")
    bad = 0
    for line in HASHES.read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        digest, path = line.split(maxsplit=1)
        frozen_ok = sha(git("show", f"{freeze}:{path}")) == digest
        now = ROOT / path
        now_ok = now.exists() and sha(now.read_bytes()) == digest
        if not frozen_ok:
            bad += 1
            state = "MISMATCH at freeze"
        elif now_ok:
            state = "ok"
        else:
            last = git("log", "-1", "--format=%h %s", "--", path).decode().strip()
            state = f"ok at freeze; changed since ({last[:70]})"
        print(f"{state:60s} {path}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
