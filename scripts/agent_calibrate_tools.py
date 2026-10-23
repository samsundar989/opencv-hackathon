"""Calibrate the agent tools' view-comparison thresholds on real history frames (W2).

Samples 6 clean registered daylight frames (segment "main") and 6 frames from unlinked view-change segments that
failed registration, per site (seed 1), runs `compare_to_last_good` and `image_quality` against the protocol-cut
bundle, and writes one row per frame. The thresholds in `agent/tools.py` (SAME_RESP, SAME_SHIFT_PX) were read off
this table. Frames listed here are excluded from the agent-eval episode set (scripts/agent_build_episodes.py).

  python scripts/agent_calibrate_tools.py          (light: ~160 frames, < 1 min, runs directly)
Output: results/agent_eval/tool_calibration.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from riversight.agent import tools  # noqa: E402

BUNDLES = ROOT / "data" / "derived" / "agent_bundles"
OUT = ROOT / "results" / "agent_eval" / "tool_calibration.csv"


def main():
    rows = []
    for cam in sorted(p.name for p in BUNDLES.iterdir() if (p / "meta.json").exists()):
        reg = pd.read_parquet(ROOT / "data" / "derived" / cam / "history" / "registration.parquet")
        reg = reg[~reg["night"].astype(bool)]
        pools = {"clean": reg[reg["ok"].astype(bool) & (reg["segment"] == "main")],
                 "newview": reg[reg["segment"].astype(str).str.endswith("unlinked") & ~reg["ok"].astype(bool)]}
        ctx = tools.ToolContext(mode="eval", bundle_root=BUNDLES, event={"cam_id": cam, "reading": {}})
        for lab, df in pools.items():
            for fn in df["filename"].sample(min(6, len(df)), random_state=1):
                k = f"data/raw/720/{cam}/{fn}"
                c = tools.call(ctx, "compare_to_last_good", {"cam": cam, "frame_key": k})
                q = tools.call(ctx, "image_quality", {"frame_key": k})
                if "error" in c:
                    continue
                rows.append({"cam_id": cam, "filename": fn, "label": lab, "phase_response": c["phase_response"],
                             "shift_px": c["shift_px"], "static_sim": c["static_structure_similarity"],
                             "verdict": c["verdict"], "usable": q["usable"], "issues": ",".join(q["issues"]),
                             "texture_loss": q["texture_loss_frac"]})
    d = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(OUT, index=False)
    same = d["verdict"] == "same view"
    for lab in ("clean", "newview"):
        m = d["label"] == lab
        print(f"{lab:8s} n={m.sum():3d}  'same view' {same[m].mean():.2f}  usable {d.loc[m, 'usable'].mean():.2f}  "
              f"median response {d.loc[m, 'phase_response'].median():.3f}  median shift {d.loc[m, 'shift_px'].median():.1f}px")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()
