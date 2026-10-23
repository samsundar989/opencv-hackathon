"""River Steward evaluation harness (W2): run arms over the frozen episode set, score, report.

  python scripts/agent_eval.py freeze                       hash episodes + prompt/rules/tools -> FROZEN.json
  python scripts/agent_eval.py run --arm rules --reps 3 [--final] [--limit N] [--jobs 6]
  python scripts/agent_eval.py report                       results.csv + REPORT.md from the final runs

Arms: rules (b) · haiku (a) · haiku_noev (c: LLM with flags-only tools) · sonnet (a on a second model).
`--final` refuses to run unless the episode set, prompt, rules, tools and scorer match FROZEN.json; final runs
write results/agent_eval/runs/<arm>.jsonl, other runs go to runs/agent_eval/dev/ (gitignored).

Tool outputs are deterministic per episode, so they are cached on disk (keyed by the tools' code hash) and every
arm and repeat sees identical OpenCV evidence; reported tool latency is the original uncached compute time.
Batch runs go through worker-q (D-0008, high priority):
  workerq submit --project riversight --priority high --gpus 0 --ram 4 --cpus 4 --node local -- \
    C:/Users/samsu/AppData/Local/Python/pythoncore-3.14-64/python.exe scripts/agent_eval.py run --arm haiku --reps 3 --final
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from riversight import agent  # noqa: E402
from riversight.agent import fleet, llm, schema, tools  # noqa: E402
from riversight.agent.store import Sink  # noqa: E402

RES = ROOT / "results" / "agent_eval"
EPISODES = RES / "episodes.jsonl"
FROZEN = RES / "FROZEN.json"
BUNDLES = ROOT / "data" / "derived" / "agent_bundles"
WORK = ROOT / "runs" / "agent_eval"
ARMS = {"rules": dict(use_llm=False, evidence="full", model=None),
        "haiku": dict(use_llm=True, evidence="full", model=llm.HAIKU),
        "haiku_noev": dict(use_llm=True, evidence="flags_only", model=llm.HAIKU),
        "sonnet": dict(use_llm=True, evidence="full", model=llm.SONNET)}
CONTROL_KINDS = ("control_view", "control_disagree", "control_rise", "view_transient", "view_shift")
FROZEN_FILES = ["src/riversight/agent/llm.py", "src/riversight/agent/rules.py", "src/riversight/agent/tools.py",
                "src/riversight/agent/schema.py", "src/riversight/agent/fleet.py", "scripts/agent_eval.py"]


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_episodes():
    return [json.loads(line) for line in EPISODES.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---- scoring ----------------------------------------------------------------------------------------

def score(ep: dict, d: dict) -> dict:
    types = set(schema.action_types(d))
    req = set(ep["expected_actions"])
    forb = set(ep["forbidden_actions"])
    args_ok = True
    for t, want in (ep.get("expected_args") or {}).items():
        a = next((x for x in d["actions"] if x["type"] == t), None)
        if a is None or any(str((a.get("args") or {}).get(k, "")).lower() != str(v).lower() for k, v in want.items()):
            args_ok = False
    missing, hit = sorted(req - types), sorted(types & forb)
    return {"success": bool(not missing and not hit and args_ok), "missing": "+".join(missing), "forbidden_hit": "+".join(hit),
            "args_ok": args_ok, "escalations": int(sum(a["needs_approval"] for a in d["actions"])),
            "unneeded_escalations": int(sum(a["needs_approval"] and a["type"] not in req for a in d["actions"])),
            "actions": "+".join(sorted(types))}


def kendall_tau(pred: list, truth: list) -> float:
    pos = {k: i for i, k in enumerate(pred)}
    c = d = 0
    for i in range(len(truth)):
        for j in range(i + 1, len(truth)):
            if pos[truth[i]] < pos[truth[j]]:
                c += 1
            else:
                d += 1
    return (c - d) / max(c + d, 1)


# ---- tool cache -------------------------------------------------------------------------------------

class ToolCache:
    def __init__(self):
        self.dir = WORK / "cache" / sha(ROOT / "src/riversight/agent/tools.py")[:12]
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.mem: dict[str, dict] = {}

    def _load(self, eid):
        if eid not in self.mem:
            p = self.dir / f"{eid}.json"
            self.mem[eid] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        return self.mem[eid]

    def wrap(self, real_call):
        def call(ctx, name, args):
            if ctx.evidence != "full" or name == "render_wet_overlay":
                return real_call(ctx, name, args)
            eid = ctx.event["event_id"]
            a = {k: v for k, v in (args or {}).items() if v is not None}
            if name in ("reregister_fullres", "compare_to_last_good", "estimate_stage", "fetch_recent_frames"):
                a.setdefault("cam", ctx.event["cam_id"])
            key = name + json.dumps(a, sort_keys=True, default=str)
            with self.lock:
                hit = self._load(eid).get(key)
            if hit is not None:
                tools._tl.ms = hit["ms"]
                return hit["res"]
            t0 = time.perf_counter()
            res = real_call(ctx, name, args)
            ms = round(1000 * (time.perf_counter() - t0))
            tools._tl.ms = ms
            with self.lock:
                c = self._load(eid)
                c[key] = {"res": res, "ms": ms}
                (self.dir / f"{eid}.json").write_text(json.dumps(c, default=str), encoding="utf-8")
            return res
        return call


# ---- running ----------------------------------------------------------------------------------------

def make_ctx(ep: dict, evidence: str, sink: Sink) -> tools.ToolContext:
    c = ep["ctx"]
    return tools.ToolContext(mode="eval", evidence=evidence, bundle_root=BUNDLES, sink=sink, now=pd.Timestamp(c["now"]),
                             gauge_fault=c.get("gauge_fault"), bank_exclude=tuple(c.get("bank_exclude") or ()),
                             event=ep["event"])


def run_episode(ep, arm, rep, sink):
    cfg = ARMS[arm]
    ctx = make_ctx(ep, cfg["evidence"], sink)
    t0 = time.perf_counter()
    d = agent.handle(ep["event"], ctx=ctx, model=cfg["model"], use_llm=cfg["use_llm"], record=False)
    wall = round(1000 * (time.perf_counter() - t0))
    tool_ms = sum(s.get("ms", 0) for s in d.get("steps", []))
    return {"episode_id": ep["episode_id"], "kind": ep["kind"], "source": ep["source"], "cam_id": ep["cam_id"],
            "arm": arm, "rep": rep, "decided_by": d["decided_by"], "model": d.get("model"),
            "fallback": d.get("fallback_reason", ""), "n_steps": len(d.get("steps", [])),
            "tools": "+".join(s["tool"] for s in d.get("steps", [])), "tokens_in": d.get("tokens_in", 0),
            "tokens_out": d.get("tokens_out", 0), "usd": d.get("usd", 0.0), "llm_ms": d.get("llm_ms", 0),
            "tool_ms": tool_ms, "wall_ms": wall, "latency_ms": d.get("llm_ms", 0) + tool_ms,
            **score(ep, d), "rationale": d.get("rationale", ""), "decision": d}


def run(arm: str, reps: int, final: bool, limit: int | None, jobs: int, only: list[str] | None):
    eps = load_episodes()
    if final:
        fz = json.loads(FROZEN.read_text(encoding="utf-8"))
        cur = current_hashes()
        bad = [k for k in fz["hashes"] if fz["hashes"][k] != cur.get(k)]
        if bad:
            sys.exit(f"refusing --final: changed since freeze: {bad}")
    single = [e for e in eps if e["kind"] != "fleet"]
    fleets = [e for e in eps if e["kind"] == "fleet"]
    if only:
        single = [e for e in single if any(o in e["episode_id"] for o in only)]
    if limit:
        single = single[:limit]
    out_dir = RES / "runs" if final else WORK / "dev"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{arm}.jsonl"
    if final and out.exists():
        sys.exit(f"refusing: {out} exists (final arms run once; delete it deliberately to re-run)")
    tools.call = ToolCache().wrap(tools.call)
    sink = Sink(local_dir=WORK / "sink" / arm, bucket="")
    rows = []
    total = reps * (len(single) + len(fleets))
    done = 0
    prog = os.environ.get("WORKERQ_PROGRESS")
    with out.open("w", encoding="utf-8") as f:
        for rep in range(reps):
            decisions = {}
            with ThreadPoolExecutor(jobs) as ex:
                futs = {ex.submit(run_episode, ep, arm, rep, sink): ep for ep in single}
                for fu in as_completed(futs):
                    r = fu.result()
                    decisions[r["episode_id"]] = r["decision"]
                    rows.append(r)
                    f.write(json.dumps(r, default=str) + "\n")
                    f.flush()
                    done += 1
                    if prog:
                        Path(prog).write_text(f"{done / total:.4f}")
                    print(f"[{arm} r{rep}] {r['episode_id']:<60s} {'OK ' if r['success'] else 'BAD'} {r['actions']:<32s} "
                          f"{r['decided_by']} {r['latency_ms']}ms ${r['usd']:.4f}", flush=True)
            for fe in fleets:
                if not all(m in decisions for m in fe["members"]):
                    continue
                items = [{"key": m, "event": next(e for e in single if e["episode_id"] == m)["event"], "decision": decisions[m]}
                         for m in fe["members"]]
                try:
                    rk = fleet.rank_llm(items, model=ARMS[arm]["model"]) if ARMS[arm]["use_llm"] else fleet.rank_rules(items)
                except Exception as e:                                            # noqa: BLE001
                    rk = {**fleet.rank_rules(items), "fallback": f"{type(e).__name__}: {e}"[:200]}
                r = {"episode_id": fe["episode_id"], "kind": "fleet", "source": fe["source"], "arm": arm, "rep": rep,
                     "order": rk["order"], "expected_order": fe["expected_order"], "top1": rk["order"][0] == fe["expected_order"][0],
                     "tau": kendall_tau(rk["order"], fe["expected_order"]), "decided_by": rk["decided_by"],
                     "fallback": rk.get("fallback", ""), "tokens_in": rk.get("tokens_in", 0), "tokens_out": rk.get("tokens_out", 0),
                     "usd": rk.get("usd", 0.0), "reasons": rk.get("reasons", {})}
                rows.append(r)
                f.write(json.dumps(r, default=str) + "\n")
                done += 1
    s = pd.DataFrame([r for r in rows if r["kind"] != "fleet"])
    print(f"\n{arm}: success {s['success'].mean():.3f} over {len(s)} runs; fallbacks {int((s['fallback'] != '').sum())}; "
          f"tokens {s['tokens_in'].sum() + s['tokens_out'].sum():,}; ${s['usd'].sum():.3f}; -> {out}")


# ---- freeze / report --------------------------------------------------------------------------------

def current_hashes() -> dict:
    h = {"episodes.jsonl": sha(EPISODES)}
    h.update({f: sha(ROOT / f) for f in FROZEN_FILES})
    return h


def freeze():
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    eps = load_episodes()
    doc = {"frozen_at_utc": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "git_head": commit,
           "n_episodes": len(eps), "n_single": sum(e["kind"] != "fleet" for e in eps),
           "n_real": sum(e["source"] == "real" for e in eps), "hashes": current_hashes(),
           "models": {"haiku": llm.HAIKU, "sonnet": llm.SONNET}}
    FROZEN.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(json.dumps(doc, indent=2))


def _fmt(m, lo, hi, pct=True):
    f = (lambda x: f"{100 * x:.1f}%") if pct else (lambda x: f"{x:.3g}")
    return f"{f(m)} ({f(lo)}–{f(hi)})"


def report():
    files = sorted((RES / "runs").glob("*.jsonl"))
    if not files:
        sys.exit("no final runs yet")
    rows = [json.loads(line) for p in files for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    s = pd.DataFrame([r for r in rows if r["kind"] != "fleet"]).drop(columns=["decision"], errors="ignore")
    fl = pd.DataFrame([r for r in rows if r["kind"] == "fleet"])
    s.drop(columns=["rationale"]).to_csv(RES / "results.csv", index=False)
    fz = json.loads(FROZEN.read_text(encoding="utf-8")) if FROZEN.exists() else {}
    arms = [a for a in ARMS if a in set(s["arm"])]
    L = ["# River Steward — agent evaluation", "",
         f"Episode set: `results/agent_eval/episodes.jsonl`, sha256 `{fz.get('hashes', {}).get('episodes.jsonl', '?')}` "
         f"(frozen {fz.get('frozen_at_utc', '?')}, git {fz.get('git_head', '?')[:9]}); {fz.get('n_single', '?')} single-camera "
         f"episodes ({fz.get('n_real', '?')} real) + {len(set(fl['episode_id'])) if len(fl) else 0} fleet cycles. "
         "Expected actions were written by `scripts/agent_build_episodes.py` before any arm ran. Every number below is "
         "computed by `scripts/agent_eval.py report` from `results/agent_eval/runs/*.jsonl`.", "",
         "Arms: **rules** = deterministic policy (`agent/rules.py`); **haiku** = Bedrock Claude Haiku 5.5 agent with the "
         "OpenCV tools; **haiku_noev** = the same agent whose tools return only the reading's flags (no OpenCV evidence); "
         "**sonnet** = the agent on Claude Sonnet 5.5. Each arm ran every episode "
         f"{int(s.groupby('arm')['rep'].nunique().max())}×; cells show mean over repeats (min–max across repeats).", "",
         "## Headline", "", "| arm | task success | real episodes | synthetic | false-action rate on clean controls | "
         "unneeded escalations / episode | fleet top-1 | fleet Kendall τ | LLM fallbacks | p50 / p95 latency (s) | tokens / episode | $ / episode (est.) |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in arms:
        x = s[s["arm"] == a]
        per = x.groupby("rep")
        succ = per["success"].mean()
        real = x[x["source"] == "real"].groupby("rep")["success"].mean()
        syn = x[x["source"] == "synthetic"].groupby("rep")["success"].mean()
        ctrl = x[x["kind"].isin(CONTROL_KINDS)]
        far = ctrl.groupby("rep").apply(lambda g: (g["forbidden_hit"].fillna("") != "").mean(), include_groups=False)
        une = per["unneeded_escalations"].mean()
        f = fl[fl["arm"] == a] if len(fl) else fl
        top1 = f.groupby("rep")["top1"].mean() if len(f) else pd.Series([np.nan])
        tau = f.groupby("rep")["tau"].mean() if len(f) else pd.Series([np.nan])
        tok = (x["tokens_in"] + x["tokens_out"]).mean()
        usd = (x["usd"].sum() + (f["usd"].sum() if len(f) else 0)) / max(len(x), 1)
        L.append(f"| {a} | {_fmt(succ.mean(), succ.min(), succ.max())} | {_fmt(real.mean(), real.min(), real.max())} | "
                 f"{_fmt(syn.mean(), syn.min(), syn.max())} | {_fmt(far.mean(), far.min(), far.max())} | "
                 f"{une.mean():.2f} | {_fmt(top1.mean(), top1.min(), top1.max())} | {tau.mean():.2f} | "
                 f"{int((x['fallback'].fillna('') != '').sum())}/{len(x)} | {x['latency_ms'].quantile(0.5) / 1000:.1f} / "
                 f"{x['latency_ms'].quantile(0.95) / 1000:.1f} | {tok:,.0f} | {usd:.4f} |")
    L += ["", "## Task success by episode kind", "", "| kind | source | n | " + " | ".join(arms) + " |",
          "|---|---|---|" + "---|" * len(arms)]
    for (k, src), g in s.groupby(["kind", "source"]):
        n = g["episode_id"].nunique()
        cells = []
        for a in arms:
            ga = g[g["arm"] == a]
            cells.append(f"{100 * ga['success'].mean():.0f}%" if len(ga) else "–")
        L.append(f"| {k} | {src} | {n} | " + " | ".join(cells) + " |")
    L += ["", "## Detection in cycles (real registration loss)", "",
          "Onset = the first flagged cycle of a real registration-loss segment; persistent = the previous two readings "
          "were already flagged. Detection = QUARANTINE in that cycle; escalation = recalibration ticket.", "",
          "| arm | quarantined at onset | ticket at onset (premature) | quarantined when persistent | ticket when persistent |", "|---|---|---|---|---|"]
    for a in arms:
        x = s[s["arm"] == a]
        on, pe = x[x["kind"] == "reg_loss_onset"], x[x["kind"] == "reg_loss_persist"]
        q = lambda g, t: f"{100 * g['actions'].str.contains(t).mean():.0f}%" if len(g) else "–"   # noqa: E731
        L.append(f"| {a} | {q(on, 'QUARANTINE')} | {q(on, 'OPEN_TICKET')} | {q(pe, 'QUARANTINE')} | {q(pe, 'OPEN_TICKET')} |")
    L += ["", "## Failure cases", ""]
    for a in arms:
        bad = s[(s["arm"] == a) & ~s["success"]]
        if not len(bad):
            continue
        L.append(f"**{a}** — {bad['episode_id'].nunique()} episodes failed at least once:")
        L.append("")
        for eid, g in list(bad.groupby("episode_id"))[:14]:
            r = g.iloc[0]
            L.append(f"- `{eid}` ({len(g)}/{s[(s['arm'] == a) & (s['episode_id'] == eid)].shape[0]} repeats): did "
                     f"`{r['actions']}`" + (f", missing `{r['missing']}`" if r["missing"] else "") +
                     (f", forbidden `{r['forbidden_hit']}`" if r["forbidden_hit"] else "") +
                     (", wrong args" if not r["args_ok"] else "") + f". *{str(r['rationale'])[:220]}*")
        L.append("")
    L += ["## Notes", "",
          "- Costs are estimates at Anthropic first-party list prices (Haiku 5.5 $0.10/$0.50, Sonnet 5.5 $2/$10 per MTok); "
          "Bedrock bills its own rates. Latency = model time + original (uncached) tool compute time.",
          "- Temperature is not set: Claude 5.5 models reject non-default sampling parameters, so repeats show the spread.",
          "- Real episodes use cached USGS HIVIS frames and gauge records; synthetic faults are labelled `synthetic` "
          "(`agent/faults.py`, `tools.apply_gauge_fault`). No real gauge outage > 3 h exists in the 20 sites' history, so "
          "all gauge-stale episodes are synthetic dropouts on real frames.",
          "- Tools use protocol-cut site bundles (training < 2026-10-03), so test-window frames are out-of-sample for the "
          "scene model. Test-day frames serve here only as agent inputs; nothing in the stage model was refit or tuned on them.",
          "- `rise_*` labels are hindsight: an alert is expected iff the gauge reached the site's calibration p90 within 6 h."]
    (RES / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:20]))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--arm", choices=list(ARMS), required=True)
    r.add_argument("--reps", type=int, default=3)
    r.add_argument("--final", action="store_true")
    r.add_argument("--limit", type=int)
    r.add_argument("--only", nargs="*")
    r.add_argument("--jobs", type=int, default=6)
    sub.add_parser("freeze")
    sub.add_parser("report")
    a = ap.parse_args()
    if a.cmd == "run":
        run(a.arm, a.reps, a.final, a.limit, a.jobs, a.only)
    elif a.cmd == "freeze":
        freeze()
    else:
        report()


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()
