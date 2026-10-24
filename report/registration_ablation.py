"""Registration ablation per site (PLAN_2026-10-23 Technical #3): ORB vs ALIKED+LightGlue vs the reference bank.

Two windows, both daylight frames only:
  * 30-day kill-test window (SLICE_01 cascade, results/kill_test/registration_summary.csv):
      ORB + MAGSAC alone → + ALIKED + LightGlue → + chaining through a registered neighbour.
  * 12-month calibration history (local index data/derived/<cam>/history/{registration.parquet,segments.csv}):
      main reference only → + a bank of per-view references (one per run of frames the main reference
      could not register) → frames linked back to the main view (usable for calibration).

A "segment" is a run of frames the main reference failed on. Its frames are re-registered to the segment's own
reference (`ok_raw`); `linked` segments were also registered back to the main reference, so their frames count
as calibration data. Frames in segments that the main reference registered are counted from `main_ok_rate`.

    python report/registration_ablation.py   → results/registration_ablation.csv, results/registration_ablation_summary.json
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
DER = ROOT / "data" / "derived"


def history_row(cam: str) -> dict:
    r = pd.read_parquet(DER / cam / "history" / "registration.parquet")
    seg = pd.read_csv(DER / cam / "history" / "segments.csv")
    d = r[~r.night.astype(bool)]
    main = d.segment == "main"
    in_seg = ~main
    main_ok = int((main & d.ok.astype(bool)).sum())
    seg_by_main = int(round(float((seg.main_ok_rate * seg.n_frames).sum()))) if len(seg) else 0
    bank_ok = int((in_seg & d.ok_raw.astype(bool)).sum())
    linked_ok = int((in_seg & d.ok.astype(bool)).sum())
    n = len(d)
    return {"hist_day_frames": n, "hist_seg_frames": int(in_seg.sum()), "hist_segments": len(seg),
            "hist_segments_linked": int(seg.linked.astype(bool).sum()) if len(seg) else 0,
            "hist_main_only": main_ok + seg_by_main,
            "hist_with_bank": main_ok + max(bank_ok, seg_by_main),
            "hist_usable_for_calibration": main_ok + linked_ok}


def main() -> None:
    reg = pd.read_csv(RES / "kill_test" / "registration_summary.csv")
    rows = []
    for _, s in reg.iterrows():
        row = {"cam_id": s.site, "day_frames_30d": int(s.day), "orb_30d": int(s.orb),
               "orb_plus_aliked_30d": int(s.orb + s.aliked_lightglue), "cascade_30d": int(s.registered),
               "orb_rate_30d": s.orb / s.day, "orb_aliked_rate_30d": (s.orb + s.aliked_lightglue) / s.day,
               "cascade_rate_30d": s.registered / s.day}
        if (DER / s.site / "history" / "registration.parquet").exists():
            h = history_row(s.site)
            row.update(h)
            n = max(h["hist_day_frames"], 1)
            row.update({"hist_main_only_rate": h["hist_main_only"] / n, "hist_with_bank_rate": h["hist_with_bank"] / n,
                        "hist_usable_rate": h["hist_usable_for_calibration"] / n})
        rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(RES / "registration_ablation.csv", index=False, float_format="%.4f")

    tot = lambda c: int(df[c].sum())  # noqa: E731
    summ = {
        "source": "results/registration_ablation.csv (report/registration_ablation.py)",
        "window_30d": {"day_frames": tot("day_frames_30d"),
                       "orb_rate": round(tot("orb_30d") / tot("day_frames_30d"), 3),
                       "orb_aliked_rate": round(tot("orb_plus_aliked_30d") / tot("day_frames_30d"), 3),
                       "cascade_rate": round(tot("cascade_30d") / tot("day_frames_30d"), 3),
                       "sites_orb_below_50pct": int((df.orb_rate_30d < 0.5).sum()),
                       "sites_cascade_at_least_90pct": int((df.cascade_rate_30d >= 0.9).sum())},
    }
    if "hist_day_frames" in df:
        h = df.dropna(subset=["hist_day_frames"])
        summ["history_12m"] = {
            "sites": int(len(h)), "day_frames": int(h.hist_day_frames.sum()),
            "segment_frames": int(h.hist_seg_frames.sum()), "segments": int(h.hist_segments.sum()),
            "segments_linked": int(h.hist_segments_linked.sum()),
            "main_only_rate": round(float(h.hist_main_only.sum() / h.hist_day_frames.sum()), 3),
            "with_bank_rate": round(float(h.hist_with_bank.sum() / h.hist_day_frames.sum()), 3),
            "usable_rate": round(float(h.hist_usable_for_calibration.sum() / h.hist_day_frames.sum()), 3),
            "sites_bank_gain_ge_5pts": int(((h.hist_with_bank_rate - h.hist_main_only_rate) >= 0.05).sum()),
        }
    (RES / "registration_ablation_summary.json").write_text(json.dumps(summ, indent=2) + "\n", encoding="utf-8")
    print(df[["cam_id", "orb_rate_30d", "orb_aliked_rate_30d", "cascade_rate_30d", "hist_main_only_rate",
              "hist_with_bank_rate", "hist_usable_rate"]].round(3).to_string(index=False))
    print(json.dumps(summ, indent=2))


if __name__ == "__main__":
    main()
