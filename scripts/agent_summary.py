"""results/agent_eval/summary.json for the /judge page (W2). Every number is computed from committed files:
results/agent_eval/runs/*.jsonl (final arms), FROZEN.json (episode-set hash), replay/*_timeline.csv (flood replays).
/judge prints this JSON verbatim, so keys are written to be read by a person.

  python scripts/agent_summary.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results" / "agent_eval"
CONTROL_KINDS = ("control_view", "control_disagree", "control_rise", "view_transient", "view_shift")
ARM_NAMES = {"rules": "deterministic rules policy (baseline)", "haiku": "Claude agent with OpenCV tools",
             "haiku_noev": "same Claude agent, tools return only the flags (no OpenCV evidence)",
             "sonnet": "Claude agent with OpenCV tools, second model"}


def pct(x) -> float | None:
    return None if x is None or not np.isfinite(x) else round(100 * float(x), 1)


def arm_block(arm: str, s: pd.DataFrame, f: pd.DataFrame) -> dict:
    per = s.groupby("rep")["success"].mean()
    ctrl = s[s["kind"].isin(CONTROL_KINDS)]
    far = ctrl.groupby("rep")["forbidden_hit"].apply(lambda x: (x.fillna("") != "").mean())
    model = s["model"].dropna().iloc[0] if s["model"].notna().any() else None
    return {
        "arm": ARM_NAMES.get(arm, arm), "model": model, "repeats": int(s["rep"].nunique()),
        "task_success_pct": {"mean": pct(per.mean()), "min": pct(per.min()), "max": pct(per.max())},
        "task_success_real_pct": pct(s[s["source"] == "real"]["success"].mean()),
        "task_success_synthetic_pct": pct(s[s["source"] == "synthetic"]["success"].mean()),
        "false_actions_on_clean_controls_pct": pct(far.mean()),
        "unneeded_escalations_per_episode": round(float(s["unneeded_escalations"].mean()), 3),
        "fleet_triage_top1_pct": pct(f["top1"].mean()) if len(f) else None,
        "fleet_triage_kendall_tau": round(float(f["tau"].mean()), 2) if len(f) else None,
        "llm_fallbacks_to_rules": f"{int((s['fallback'].fillna('') != '').sum())}/{len(s)}",
        "latency_s": {"p50": round(s["latency_ms"].quantile(0.5) / 1000, 1), "p95": round(s["latency_ms"].quantile(0.95) / 1000, 1)},
        "tokens_per_episode": int((s["tokens_in"] + s["tokens_out"]).mean()),
        "estimated_usd_total": round(float(s["usd"].sum() + (f["usd"].sum() if len(f) else 0)), 3),
        "success_by_kind_pct": {k: pct(g["success"].mean()) for k, g in s.groupby("kind")},
    }


def replays() -> list[dict]:
    out = []
    for p in sorted((RES / "replay").glob("*_timeline.csv")):
        d = pd.read_csv(p, parse_dates=["t"])
        cam, date, policy = p.stem.replace("_timeline", "").rsplit("_", 2)
        alerts = d[d["actions"].fillna("").str.contains("DRAFT_ALERT")]
        out.append({"camera": cam, "replay_start": date, "policy": policy, "frames": len(d),
                    "flagged": int((d["flags"].fillna("") != "").sum()),
                    "first_alert_utc": alerts["t"].min().isoformat() if len(alerts) else None,
                    "alerts_drafted": len(alerts),
                    "camera_quarantined_cycles": int(d["actions"].fillna("").str.contains("QUARANTINE").sum()),
                    "figure": f"results/agent_eval/replay/{p.stem}.png"})
    return out


def main():
    fz = json.loads((RES / "FROZEN.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for p in sorted((RES / "runs").glob("*.jsonl"))
            for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    s = pd.DataFrame([r for r in rows if r["kind"] != "fleet"])
    f = pd.DataFrame([r for r in rows if r["kind"] == "fleet"])
    eps = [json.loads(line) for line in (RES / "episodes.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    single = [e for e in eps if e["kind"] != "fleet"]
    arms = {a: arm_block(a, g, f[f["arm"] == a] if len(f) else f) for a, g in s.groupby("arm")} if len(s) else {}
    effect = None
    if "haiku" in arms and "haiku_noev" in arms:
        effect = {"what": "task success with OpenCV evidence minus without (same model, same episodes)",
                  "points": round(arms["haiku"]["task_success_pct"]["mean"] - arms["haiku_noev"]["task_success_pct"]["mean"], 1)}
    pending = [a for a in ("haiku", "haiku_noev", "sonnet") if a not in arms]
    doc = {
        "title": "River Steward — fleet agent evaluation",
        "status": "final" if not pending else f"rules baseline final; LLM arms pending: {', '.join(pending)}",
        "episode_set": {"file": "results/agent_eval/episodes.jsonl", "sha256": fz["hashes"]["episodes.jsonl"],
                        "frozen_utc": fz["frozen_at_utc"], "single_camera_episodes": len(single),
                        "real": sum(e["source"] == "real" for e in single),
                        "synthetic_labelled": sum(e["source"] == "synthetic" for e in single),
                        "clean_controls": sum(e["kind"] in CONTROL_KINDS for e in single),
                        "fleet_cycles": sum(e["kind"] == "fleet" for e in eps),
                        "expected_actions_written": "by the builder, before any arm ran"},
        "arms": arms,
        "opencv_evidence_effect": effect,
        "flood_replays": replays(),
        "honest_limits": [
            "Gauge-stale episodes are synthetic dropouts on real frames: no real outage > 3 h exists in the 20 histories.",
            "Above its calibrated range a camera saturates and cannot measure the flood; the agent trusts the gauge and "
            "publishes only a lower bound when the gauge is out.",
            "Re-anchoring is tested on 10 real episodes, 8 from one camera (Pecatonica).",
            "Costs are estimates at Anthropic list prices; Bedrock bills its own rates.",
        ],
        "sources": ["results/agent_eval/REPORT.md", "results/agent_eval/runs/*.jsonl", "results/agent_eval/FROZEN.json",
                    "results/agent_eval/runs_v1/README.md (superseded runs and why)"],
    }
    (RES / "summary.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(json.dumps({k: doc[k] for k in ("status", "episode_set")}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
