"""Time the judge path on a clean checkout and record it (docs/REPRODUCE.md quotes these times).

Steps, each timed: clone → venv → pip install -e ".[dev]" → pytest → re-derive the fleet summary and the
report tables from the committed predictions → check every doc number → `git diff --exit-code results report`
(the re-derived files must be byte-identical to the committed ones).

    python report/time_fresh_clone.py --dest <empty scratch dir>   → results/repro/fresh_clone_times.json
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "git@github.com:samsundar989/opencv-hackathon.git"


def run(name: str, cmd: list[str], cwd: Path, log: list[dict]) -> bool:
    t = time.perf_counter()
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    dt = time.perf_counter() - t
    tail = (p.stdout + p.stderr).strip().splitlines()[-3:]
    log.append({"step": name, "cmd": " ".join(cmd), "seconds": round(dt, 1), "ok": p.returncode == 0, "tail": tail})
    print(f"{name:28s} {dt:7.1f} s  {'ok' if p.returncode == 0 else 'FAILED'}  {tail[-1] if tail else ''}", flush=True)
    return p.returncode == 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", type=Path, required=True)
    ap.add_argument("--url", default=URL)
    args = ap.parse_args()
    repo = args.dest / "riversight"
    if repo.exists():
        shutil.rmtree(repo)
    args.dest.mkdir(parents=True, exist_ok=True)
    log: list[dict] = []
    run("git clone", ["git", "clone", "-q", args.url, str(repo)], args.dest, log)
    py = repo / ".venv" / ("Scripts" if os.name == "nt" else "bin") / "python"
    steps = [
        ("venv", [sys.executable, "-m", "venv", ".venv"]),
        ("pip install -e .[dev]", [str(py), "-m", "pip", "install", "-q", "-e", ".[dev]"]),
        ("pytest -q", [str(py), "-m", "pytest", "-q", "-p", "no:warnings"]),
        ("summarize_results", [str(py), "report/summarize_results.py"]),
        ("build_report_tables", [str(py), "report/build_report_tables.py"]),
        ("check_report_numbers", [str(py), "scripts/check_report_numbers.py"]),
        ("results byte-identical", ["git", "diff", "--exit-code", "--stat", "results", "report"]),
    ]
    for name, cmd in steps:
        run(name, cmd, repo, log)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    out = {"date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "commit": commit,
           "python": platform.python_version(), "platform": platform.platform(),
           "total_seconds": round(sum(s["seconds"] for s in log), 1), "steps": log}
    dst = ROOT / "results" / "repro" / "fresh_clone_times.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"total {out['total_seconds']} s -> {dst}")


if __name__ == "__main__":
    main()
