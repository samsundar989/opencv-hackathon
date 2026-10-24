"""SPRINT W5 A.4: how long until a new camera is useful? CV MAE vs days of calibration.

For each site, the test set is fixed: its last 2 calendar months of calibration data with ≥ 20 frames spread over
≥ 14 days. For test month M
and calibration length N ∈ {14, 30, 60, 90, 180, 365} days, the frozen D-0007 setting is trained on frames in
[M − 7 d − N, M − 7 d) and scored on M (riversight.onboard.cv.fewshot). N = 365 means "everything available", which
is ≤ ~10 months before the test months.

Sites: the kill-test sites with ≥ 300 calibration days (history before 2026-10-03 only; the frozen test days are
never read), plus any onboarded site with status done (window to 2026-10-23), up to --n sites.

  python scripts/onboard_fewshot.py --n 10        → results/onboarding/fewshot.csv, fewshot_summary.csv
"""
from __future__ import annotations

import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from riversight.onboard import W_END  # noqa: E402

DATA = Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))
RES = Path(os.environ.get("RIVERSIGHT_RESULTS", ROOT / "results")) / "onboarding"   # absolute when run from a worker-q snapshot
DAYS = (14, 30, 60, 90, 180, 365)
KILL_CUT = pd.Timestamp("2026-10-03", tz="UTC")


def one(cam: str, cut: str, source: str) -> list[dict]:
    from riversight.onboard.cv import fewshot
    return [{**r, "source": source} for r in fewshot(DATA, cam, pd.Timestamp(cut), DAYS)]


def pick_sites(n: int) -> list[tuple[str, str, str]]:
    cov = pd.read_csv(ROOT / "results" / "history" / "coverage_summary.csv")
    kill = cov[cov["days_with_selected_frames"] >= 300].sort_values("days_with_selected_frames", ascending=False)
    out = [(c, str(KILL_CUT), "kill_test_history") for c in kill["cam_id"]]
    for p in sorted(RES.glob("*.json")):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if r.get("status") == "done" and (r.get("cv") or {}).get("cal_days", 0) >= 300:
            out.append((r["cam_id"], str(pd.Timestamp(W_END)), "onboarded"))
    return out[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    sites = pick_sites(a.n)
    rows = []
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(one, *s): s[0] for s in sites}
        for k, fu in enumerate(as_completed(futs), 1):
            try:
                rows += fu.result()
                print(f"{futs[fu]}: done", flush=True)
            except Exception as e:
                print(f"{futs[fu]}: ERROR {e!r}", flush=True)
            p = os.environ.get("WORKERQ_PROGRESS")
            if p:
                Path(p).write_text(f"{k / len(sites):.4f}")
    df = pd.DataFrame(rows)
    RES.mkdir(parents=True, exist_ok=True)
    df.round(4).to_csv(RES / "fewshot.csv", index=False)
    # paired summary: only sites scored on both test months at every N, so each N sees the same frames
    full = df.groupby("cam_id")["months_scored"].min()
    paired = df[df["cam_id"].isin(full[full == 2].index)]
    summ = (paired.groupby("days").agg(sites=("cam_id", "nunique"), median_mae=("mae", "median"),
                                       median_nmae=("nmae", "median"), mean_mae=("mae", "mean"),
                                       p1_sites=("mae", lambda s: int(((s <= 0.25) | (paired.loc[s.index, "nmae"] <= 0.10)).sum())))
            .reset_index())
    summ.round(4).to_csv(RES / "fewshot_summary.csv", index=False)
    print(summ.to_string(index=False))


if __name__ == "__main__":
    main()
