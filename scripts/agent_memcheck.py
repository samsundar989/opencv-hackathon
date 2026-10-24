"""Memory + equivalence check for the agent tools (W2), run through worker-q before any batch of agent runs.

1. Peak RSS / commit of one process running every cached tool call of N episodes (default: all view and
   out-of-range episodes, which exercise reregister_fullres against the largest reference banks).
2. Each recomputed result is compared with the cached result of the same call from an earlier tools.py
   (results must be identical: the memory fix shares one ALIKED/LightGlue instance, it does not change the math).

  python scripts/agent_memcheck.py --old-cache runs/agent_eval/cache/744248d967b5 [--kinds reanchor reg_loss oor]
Output: results/agent_eval/memcheck.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-cache", type=Path, required=True)
    ap.add_argument("--kinds", nargs="*", default=["reanchor", "reg_loss", "oor", "control_view", "view_shift"])
    a = ap.parse_args()
    from riversight.agent import tools
    import agent_eval as ae
    proc, peak = psutil.Process(), {"rss": 0, "vms": 0}
    stop = False

    def watch():
        while not stop:
            m = proc.memory_info()
            peak["rss"], peak["vms"] = max(peak["rss"], m.rss), max(peak["vms"], m.vms)
            time.sleep(0.2)
    threading.Thread(target=watch, daemon=True).start()
    eps = [e for e in ae.load_episodes() if e["kind"] != "fleet" and any(e["kind"].startswith(k) for k in a.kinds)]
    same = diff = missing = 0
    diffs = []
    t0 = time.time()
    for i, ep in enumerate(eps):
        cache = a.old_cache / f"{ep['episode_id']}.json"
        if not cache.exists():
            missing += 1
            continue
        old = json.loads(cache.read_text(encoding="utf-8"))
        ctx = ae.make_ctx(ep, "full", None)
        for key, v in old.items():
            name = key[: key.index("{")]
            if name not in ("reregister_fullres", "estimate_stage", "compare_to_last_good", "image_quality"):
                continue
            args = json.loads(key[len(name):])
            new = json.loads(json.dumps(tools.call(ctx, name, args), default=str))
            if new == v["res"]:
                same += 1
            else:
                diff += 1
                diffs.append({"episode": ep["episode_id"], "tool": name})
        p = os.environ.get("WORKERQ_PROGRESS")
        if p:
            Path(p).write_text(f"{(i + 1) / len(eps):.4f}")
    stop = True
    out = {"episodes": len(eps), "missing_cache": missing, "calls_identical": same, "calls_different": diff,
           "diffs": diffs[:20], "peak_rss_gib": round(peak["rss"] / 2 ** 30, 2), "peak_vms_gib": round(peak["vms"] / 2 ** 30, 2),
           "seconds": round(time.time() - t0), "n_registrar_instances": len(tools._registrars),
           "n_cached_reference_features": len(tools._ref_feats)}
    (ROOT / "results" / "agent_eval" / "memcheck.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
