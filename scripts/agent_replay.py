"""Replay real floods through the full live loop with River Steward deciding (W2).

For each event, cached USGS HIVIS frames go through W1's live per-site step (`riversight.live.cycle.replay`:
registration, scene model + Kalman, flags, overlay, `apply_decision` -> approvals + decision log) and every flagged
reading goes to `riversight.agent.handle`. The site bundle is cut three days before the rise
(`export_site_models.py --cut`), so the camera meets this flood out-of-sample; banked references from segments
that start after the replay clock are hidden from the agent.

Outputs (results/agent_eval/replay/):
  <cam>_<date>_<llm|rules>_timeline.csv one row per replayed frame: gauge, camera ± σ, flags, decision, actions, rationale
  <cam>_<date>_<llm|rules>_timeline.png gauge vs camera with the agent's actions on a strip (drawn with OpenCV)
  <cam>_<date>_<llm|rules>_alert.jpg the first approved-for-review wet overlay the agent rendered (face-blurred)

  python scripts/agent_replay.py [--rules]      (heavy: ~240 registrations per event -> worker-q)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

EVENTS = [  # cam, bundle cut, replay window (UTC)
    ("IL_Salt_Creek_at_Wood_Dale", "2026-07-01", "2026-07-03T00:00", "2026-07-07T00:00"),
    ("WI_East_Branch_Pecatonica_River_near_Blanchardville_Bullet", "2026-04-12", "2026-04-14T06:00", "2026-04-18T00:00"),
    ("NY_East_Branch_Delaware_River_at_Hancock_Staff", "2026-07-26", "2026-07-28T12:00", "2026-08-01T00:00"),
]
OUT = ROOT / "results" / "agent_eval" / "replay"
WORK = ROOT / "runs" / "agent_replay"
COLORS = {"DRAFT_ALERT": (40, 40, 230), "OPEN_TICKET": (0, 140, 255), "QUARANTINE": (140, 140, 140),
          "SET_REFERENCE": (60, 200, 60), "MARK_PROVISIONAL": (0, 220, 220), "DENSIFY": (230, 200, 40), "NOOP": (90, 90, 90)}


def make_agent_fn(cam: str, bundles: Path, store_dir: Path, use_llm: bool):
    from riversight import agent
    from riversight.agent.store import Sink
    from riversight.agent.tools import ToolContext
    meta = json.loads((bundles / cam / "meta.json").read_text(encoding="utf-8"))

    def fn(event: dict) -> dict:
        now = pd.Timestamp(event["reading"]["t_frame"])
        later = [e["file"] for e in meta.get("extra_references", []) if pd.Timestamp(e["start"], tz="UTC") > now]
        ctx = ToolContext(mode="replay", bundle_root=bundles, sink=Sink(local_dir=store_dir, bucket=""), now=now,
                          bank_exclude=tuple(later), event=event)
        return agent.handle(event, ctx=ctx, use_llm=use_llm, record=False)
    return fn


def draw_timeline(df: pd.DataFrame, gauge: pd.Series, meta: dict, title: str, path: Path):
    W, H, L, R, T, B = 1500, 660, 80, 30, 70, 170
    img = np.full((H, W, 3), 24, np.uint8)
    t0, t1 = df["t"].min(), df["t"].max()
    g = gauge[(gauge.index >= t0) & (gauge.index <= t1)]
    vals = pd.concat([g, df["camera_ft"].dropna()])
    lo, hi = float(vals.min()) - 0.5, float(max(vals.max(), meta.get("stage_p90", 0))) + 0.5
    X = lambda t: int(L + (pd.Timestamp(t) - t0).total_seconds() / max((t1 - t0).total_seconds(), 1) * (W - L - R))  # noqa: E731
    Y = lambda v: int(T + (hi - v) / (hi - lo) * (H - T - B))                                                      # noqa: E731
    for v in np.arange(np.ceil(lo), hi, 1.0):
        cv2.line(img, (L, Y(v)), (W - R, Y(v)), (50, 50, 50), 1)
        cv2.putText(img, f"{v:.0f} ft", (8, Y(v) + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (170, 170, 170), 1, cv2.LINE_AA)
    for d in pd.date_range(t0.ceil("D"), t1, freq="D"):
        cv2.line(img, (X(d), T), (X(d), H - B), (50, 50, 50), 1)
        cv2.putText(img, d.strftime("%b %d"), (X(d) - 22, H - B + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (170, 170, 170), 1, cv2.LINE_AA)
    p90 = meta.get("stage_p90")
    if p90:
        for x in range(L, W - R, 14):
            cv2.line(img, (x, Y(p90)), (x + 7, Y(p90)), (80, 80, 220), 1)
        cv2.putText(img, f"site p90 {p90:.2f} ft", (W - R - 150, Y(p90) - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (120, 120, 240), 1, cv2.LINE_AA)
    pts = np.array([[X(t), Y(v)] for t, v in g.items()], np.int32)
    if len(pts) > 1:
        cv2.polylines(img, [pts], False, (235, 235, 235), 2, cv2.LINE_AA)
    for _, r in df.dropna(subset=["camera_ft"]).iterrows():
        s = r["sigma_ft"] or 0
        cv2.line(img, (X(r["t"]), Y(r["camera_ft"] - s)), (X(r["t"]), Y(r["camera_ft"] + s)), (0, 120, 200), 1)
        cv2.circle(img, (X(r["t"]), Y(r["camera_ft"])), 4, (0, 165, 255), -1, cv2.LINE_AA)
    # action strip
    kinds = ["DRAFT_ALERT", "OPEN_TICKET", "SET_REFERENCE", "QUARANTINE", "MARK_PROVISIONAL", "DENSIFY", "NOOP"]
    y0 = H - B + 34
    for k, kind in enumerate(kinds):
        y = y0 + k * 18
        cv2.putText(img, kind, (8, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.38, COLORS[kind], 1, cv2.LINE_AA)
        for _, r in df[df["actions"].fillna("").str.contains(kind)].iterrows():
            cv2.circle(img, (X(r["t"]), y), 5, COLORS[kind], -1, cv2.LINE_AA)
    cv2.putText(img, title, (L, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (240, 240, 240), 1, cv2.LINE_AA)
    cv2.putText(img, "white = USGS gauge   orange = camera stage +/- sigma (bundle trained before this flood)",
                (L, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)
    cv2.imwrite(str(path), img)


def replay_event(cam, cut, t0, t1, use_llm):
    tag = "llm" if use_llm else "rules"
    from riversight.agent.tools import _history_gauge
    from riversight.live import cycle
    bundles = ROOT / "data" / "derived" / "agent_bundles_replay" / cut
    store_dir = WORK / f"{cam}_{cut}_{tag}"
    shutil.rmtree(store_dir, ignore_errors=True)
    os.environ["RIVERSIGHT_LIVE_DIR"] = str(store_dir)          # the agent's tools read W1's frames from here
    rows = cycle.replay(cam, t0, t1, store_dir, make_agent_fn(cam, bundles, store_dir, use_llm), bundles)
    recs = []
    for r in rows:
        a = r.get("agent") or {}
        recs.append({"t": pd.Timestamp(r["t_frame"]), "gauge_ft": r["gauge_stage_ft"], "camera_ft": r["camera_stage_ft"],
                     "sigma_ft": r["camera_sigma_ft"], "flags": "+".join(r["flags"]), "decided_by": a.get("decided_by", ""),
                     "actions": "+".join(a.get("actions") or []), "approval_id": a.get("approval_id") or "",
                     "tokens": (a.get("tokens_in") or 0) + (a.get("tokens_out") or 0), "rationale": a.get("rationale") or ""})
    df = pd.DataFrame(recs)
    OUT.mkdir(parents=True, exist_ok=True)
    stem = f"{cam}_{t0[:10]}_{tag}"
    df.to_csv(OUT / f"{stem}_timeline.csv", index=False)
    meta = json.loads((bundles / cam / "meta.json").read_text(encoding="utf-8"))
    who = "LLM agent" if use_llm else "rules policy"
    draw_timeline(df, _history_gauge(cam), meta, f"{cam[:46]}  flood replay, River Steward ({who})", OUT / f"{stem}_timeline.png")
    alerts = sorted((store_dir / "live" / "overlays" / cam).glob("agent_*.jpg")) if (store_dir / "live" / "overlays" / cam).exists() else []
    if alerts:
        shutil.copy(alerts[0], OUT / f"{stem}_alert.jpg")
    n_flag = int((df["flags"] != "").sum())
    first_alert = df[df["actions"].str.contains("DRAFT_ALERT")]["t"].min() if len(df) else None
    above = df[df["gauge_ft"] >= meta.get("stage_p90", 1e9)]["t"].min() if len(df) else None
    print(f"{cam}: {len(df)} frames, {n_flag} flagged, decisions by {df['decided_by'].value_counts().to_dict()}, "
          f"first DRAFT_ALERT {first_alert}, gauge first >= p90 {above}")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", action="store_true", help="rules policy instead of the LLM agent")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    for cam, cut, t0, t1 in EVENTS:
        if a.only and not any(o in cam for o in a.only):
            continue
        replay_event(cam, cut, t0, t1, use_llm=not a.rules)


if __name__ == "__main__":
    main()
