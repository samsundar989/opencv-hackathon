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
             "sonnet": "Claude agent with OpenCV tools, second model",
             "hybrid": "D-0012 hybrid: rules act; Claude Sonnet 4.6 reviews gauge drift, ranks the fleet, second-opinions paging decisions"}


def pct(x) -> float | None:
    return None if x is None or not np.isfinite(x) else round(100 * float(x), 1)


def arm_block(arm: str, s: pd.DataFrame, f: pd.DataFrame) -> dict:
    per = s.groupby("rep")["success"].mean()
    ctrl = s[s["kind"].isin(CONTROL_KINDS)]
    far = ctrl.groupby("rep")["forbidden_hit"].apply(lambda x: (x.fillna("") != "").mean())
    model = s["model"].dropna().iloc[0] if s["model"].notna().any() else None
    from riversight.agent.llm import model_name
    return {
        "arm": ARM_NAMES.get(arm, arm), "model": model_name(model) if model else None, "model_id": model,
        "repeats": int(s["rep"].nunique()),
        "task_success_pct": {"mean": pct(per.mean()), "min": pct(per.min()), "max": pct(per.max())},
        "task_success_real_pct": pct(s[s["source"] == "real"]["success"].mean()),
        "task_success_synthetic_pct": pct(s[s["source"] == "synthetic"]["success"].mean()),
        "false_actions_on_clean_controls_pct": pct(far.mean()),
        "unneeded_escalations_per_episode": round(float(s["unneeded_escalations"].mean()), 3),
        "fleet_triage_top1_pct": pct(f["top1"].mean()) if len(f) else None,
        "fleet_triage_kendall_tau": round(float(f["tau"].mean()), 2) if len(f) else None,
        "llm_fallbacks_to_rules": f"{int((s['fallback'].fillna('') != '').sum())}/{len(s)}",
        "latency_s_note": "LLM latency includes client-side pacing at 9 requests/min (account quota 10/min) shared by 3 threads",
        "latency_s": {"p50": round(s["latency_ms"].quantile(0.5) / 1000, 1), "p95": round(s["latency_ms"].quantile(0.95) / 1000, 1)},
        "tokens_per_episode": int((s["tokens_in"] + s["tokens_out"]).mean()),
        "estimated_usd_total": round(float(s["usd"].sum() + (f["usd"].sum() if len(f) else 0)), 3),
        "success_by_kind_pct": {k: pct(g["success"].mean()) for k, g in s.groupby("kind")},
        "failure_modes": failure_modes(s),
    }


def failure_modes(s: pd.DataFrame) -> list[dict]:
    """Most frequent ways an arm failed: missing required / forbidden present / wrong arguments, per kind."""
    bad = s[~s["success"]].copy()
    if not len(bad):
        return []
    def why(r):
        w = []
        if r["missing"]:
            w.append("missing " + r["missing"])
        if r["forbidden_hit"]:
            w.append("forbidden " + r["forbidden_hit"])
        if not r["args_ok"]:
            w.append("wrong args")
        return "; ".join(w)
    bad["why"] = bad.apply(why, axis=1)
    top = bad.groupby(["kind", "why"]).size().sort_values(ascending=False).head(6)
    return [{"kind": k, "failure": w, "runs": int(n)} for (k, w), n in top.items()]


def oor_lower_bound_ok(r: dict) -> bool:
    """Post-hoc sensitivity rule (NOT the headline): on oor_gauge / oor_live, a MARK_PROVISIONAL whose source is
    camera_lower_bound is a lower bound, not a camera number; D-0009 only forbids a camera number."""
    if r["kind"] not in ("oor_gauge", "oor_live") or r["success"] or r["missing"] or not r["args_ok"]:
        return bool(r["success"])
    hits = set((r["forbidden_hit"] or "").split("+")) - {""}
    mp = [a for a in r["decision"]["actions"] if a["type"] == "MARK_PROVISIONAL"]
    return hits == {"MARK_PROVISIONAL"} and all((a.get("args") or {}).get("source") == "camera_lower_bound" for a in mp)


def v3_subset(rows: list[dict]) -> dict:
    """Task success of every arm on the 98 v3 episodes (the LLM-only arms ran on v3; rules and hybrid on v4 = v3 + tidal)."""
    v3 = RES / "runs_v1" / "FROZEN_v3.json"
    ids = None
    if (RES / "runs_v1" / "rules_v3_final.jsonl").exists():
        ids = {json.loads(l)["episode_id"] for l in (RES / "runs_v1" / "rules_v3_final.jsonl").read_text(encoding="utf-8").splitlines()
               if l.strip() and json.loads(l)["kind"] != "fleet"}
    if not ids:
        return {}
    df = pd.DataFrame([{k: r[k] for k in ("episode_id", "arm", "rep", "success")} for r in rows if r["kind"] != "fleet"])
    df = df[df["episode_id"].isin(ids)]
    out = {}
    for a, g in df.groupby("arm"):
        per = g.groupby("rep")["success"].mean()
        out[a] = {"task_success_pct": pct(per.mean()), "min": pct(per.min()), "max": pct(per.max()), "episodes": int(g["episode_id"].nunique())}
    return {"what": "every arm on the same 98 v3 episodes (like-for-like)", "frozen": v3.name if v3.exists() else None, "arms": out}


def hybrid_stats(rows: list[dict]) -> dict | None:
    h = [r for r in rows if r.get("arm") == "hybrid" and r["kind"] != "fleet"]
    if not h:
        return None
    dr = [r for r in h if r["decision"].get("drift_review")]
    so = [r for r in h if r["decision"].get("second_opinion") and "error" not in r["decision"]["second_opinion"]]
    return {"drift_reviews": len(dr), "drift_reviews_turned_into_gauge_ticket": sum(bool(r["decision"]["drift_review"].get("gauge_suspect")) for r in dr),
            "drift_review_kinds": {k: int(v) for k, v in pd.Series([r["kind"] for r in dr]).value_counts().items()} if dr else {},
            "second_opinions": len(so), "second_opinion_agreement_pct": pct(np.mean([r["decision"]["second_opinion"]["agrees"] for r in so])) if so else None,
            "note": "rules act; Sonnet can only replace the drift-blind quarantine with a human-approved gauge_suspect ticket; "
                    "second opinions (repeat 0 only, pre-registered for budget) are recorded, never override"}


def tidal_block(rows: list[dict]) -> dict:
    out = {}
    for a in ("rules", "hybrid"):
        g = [r for r in rows if r.get("arm") == a and r["kind"].startswith("tidal")]
        if g:
            out[a] = {k: f"{sum(r['success'] for r in g if r['kind'] == k)}/{sum(r['kind'] == k for r in g)}"
                      for k in sorted({r["kind"] for r in g})}
    return {"what": "D-0013 W2-1 tidal episodes (v4): ordinary tides must not alert; record-high days should",
            "results_runs": out,
            "finding": "Savannah's record-high days are king tides the harmonic model predicts (negative residual) and sit "
                       "between the daily-max p95 and p99, so the tidal rule does not alert; whether a predicted king tide should "
                       "page a human is a policy question (NWS issues coastal-flood advisories for them)."}


def evidence_effect(rows: list[dict], n_boot: int = 4000) -> dict | None:
    """Paired per-episode effect of OpenCV evidence: success(haiku) − success(haiku_noev), each averaged over its
    repeats, then mean over episodes with a bootstrap 95 % CI over episodes."""
    df = pd.DataFrame([{k: r[k] for k in ("episode_id", "kind", "arm", "success")} for r in rows if r["kind"] != "fleet"])
    if not {"haiku", "haiku_noev"} <= set(df["arm"]):
        return None
    m = df[df["arm"].isin(["haiku", "haiku_noev"])].pivot_table(index=["episode_id", "kind"], columns="arm", values="success", aggfunc="mean").dropna()
    d = (m["haiku"] - m["haiku_noev"]).to_numpy()
    rng = np.random.default_rng(0)
    boots = [rng.choice(d, len(d)).mean() for _ in range(n_boot)]
    by_kind = (m["haiku"] - m["haiku_noev"]).groupby(level="kind").mean().sort_values(ascending=False)
    return {"what": "Claude Haiku 4.5 with OpenCV tools minus the same model with flags-only tools; paired per episode",
            "points": round(100 * d.mean(), 1), "ci95_points": [round(100 * float(np.percentile(boots, 2.5)), 1),
                                                                 round(100 * float(np.percentile(boots, 97.5)), 1)],
            "episodes": int(len(d)), "largest_gains_by_kind_points": {k: round(100 * v, 1) for k, v in by_kind.head(5).items()},
            "largest_losses_by_kind_points": {k: round(100 * v, 1) for k, v in by_kind.tail(3).items()}}


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
    effect = evidence_effect(rows)
    sens = {}
    for a, g in s.groupby("arm"):
        recs = [r for r in rows if r.get("arm") == a and r["kind"] != "fleet"]
        sens[a] = pct(np.mean([oor_lower_bound_ok(r) for r in recs]))
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
        "like_for_like_v3": v3_subset(rows),
        "hybrid": hybrid_stats(rows),
        "tidal": tidal_block(rows),
        "opencv_evidence_effect": effect,
        "sensitivity_post_hoc": {"rule": "on real out-of-range episodes, a provisional LOWER BOUND (camera_lower_bound) published "
                                         "beside a fresh gauge counts as allowed (D-0009 forbids a camera number, not a bound). "
                                         "Post-hoc, after seeing the LLM runs; the frozen scores above are the headline.",
                                 "task_success_pct": sens},
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
