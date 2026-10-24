"""Live fleet triage: which cameras need a human now, ranked, each with its reason and the OpenCV evidence.

Writes `live/agent/triage.json` for the dashboard (W1 renders it). Called once at the end of every live cycle:

    from riversight.agent.triage import write_triage
    write_triage(store)            # W1's LocalStore / S3Store (get_json, put_json, list)

or by hand: `python -m riversight.agent.triage --s3 <bucket>` / `--local live_local`.

Ranking is deterministic (no LLM call per cycle): the most consequential thing waiting on a person first —
a flood alert awaiting approval, then a suspect gauge, a camera that needs recalibration, a provisional gap-fill,
a quarantined or above-range camera — then by how high the river is relative to the site's own calibration.
Each entry carries what the cameras' OpenCV pipeline actually measured (registration inliers and ratio,
sharpness/fog/glare, camera stage ± σ or "at least", calibrated range) and the agent's own tool findings,
so the person can see *why* without opening a log.
"""
from __future__ import annotations

import argparse
import json
import time
from typing import Any

from riversight.agent.fleet import severity

LABELS = {5: "flood alert awaiting approval", 4: "gauge looks wrong — check the gauge", 3: "needs recalibration or gap-fill review",
          2: "camera quarantined / above its calibrated range", 1: "watching (sampling more often)", 0: "no action needed"}


def _sev_of(reading: dict, decision: dict | None, pending: list[dict]) -> tuple[int, str]:
    """(severity 0–5, one-line reason)."""
    acts = (decision or {}).get("actions") or []
    s = severity({"actions": [a if isinstance(a, dict) else {"type": a, "args": {}} for a in acts]}) if decision else 0
    for p in pending:
        for a in p.get("actions", []):
            if a.get("type") == "DRAFT_ALERT":
                s = max(s, 5)
            elif a.get("type") == "OPEN_TICKET":
                s = max(s, 4 if (a.get("args") or {}).get("kind") == "gauge_suspect" else 3)
    flags = set(reading.get("flags") or [])
    if "OUT_OF_RANGE" in flags or reading.get("camera_at_least_ft") is not None:
        s = max(s, 2)
    if reading.get("status") in ("quarantined",):
        s = max(s, 2)
    if reading.get("provisional"):
        s = max(s, 3)
    why = (decision or {}).get("rationale") or reading.get("note") or ""
    if pending:
        kinds = ", ".join(sorted({a.get("type") for p in pending for a in p.get("actions", [])}))
        why = f"{kinds} pending approval. " + why
    return s, why.strip()[:400]


def _height(r: dict, meta: dict | None) -> float:
    h = r.get("gauge_stage_ft") if r.get("gauge_stage_ft") is not None else r.get("camera_stage_ft")
    if h is None or not meta:
        return 0.0
    p50, p90 = meta.get("stage_p50"), meta.get("stage_p90")
    return (h - p50) / (p90 - p50) if p50 is not None and p90 is not None and p90 > p50 else 0.0


def _last_decisions(store, day: str) -> dict[str, dict]:
    raw = store.get_bytes(f"live/agent/{day}.jsonl") or b""
    out = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("cam_id"):
            out[d["cam_id"]] = d          # file is append-only in time order: last one wins
    return out


def _pending(store) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for key in store.list("live/approvals/"):
        if not key.endswith(".json"):
            continue
        item = store.get_json(key) or {}
        if item.get("status") == "pending" and item.get("cam_id"):
            out.setdefault(item["cam_id"], []).append(item)
    return out


def _group_pending(items: list[dict]) -> list[dict]:
    """One row per pending action type: count, oldest/newest, and the newest approval id to open."""
    groups: dict[str, list[dict]] = {}
    for p in items:
        for t in {a.get("type") for a in p.get("actions", [])}:
            groups.setdefault(t, []).append(p)
    out = []
    for t, ps in sorted(groups.items()):
        ps = sorted(ps, key=lambda p: p.get("created") or "")
        out.append({"action": t, "count": len(ps), "oldest": ps[0].get("created"), "newest": ps[-1].get("created"),
                    "approval_id": ps[-1].get("approval_id")})
    return out


def evidence(r: dict, decision: dict | None) -> dict:
    reg, q = r.get("registration") or {}, r.get("quality") or {}
    return {
        "registration": {"ok": reg.get("ok"), "inliers": reg.get("inliers"), "inlier_ratio": reg.get("inlier_ratio"),
                         "method": reg.get("method"), "reference": reg.get("ref")},
        "image_quality": {"sharpness_lap_var": q.get("lap_var"), "fog_score": q.get("fog_score"), "glare_frac": q.get("glare_frac")},
        "camera_stage_ft": r.get("camera_stage_ft"), "camera_sigma_ft": r.get("camera_sigma_ft"),
        "camera_at_least_ft": r.get("camera_at_least_ft"), "calibrated_range_ft": r.get("calibrated_range_ft"),
        "gauge_stage_ft": r.get("gauge_stage_ft"), "gauge_age_min": r.get("gauge_age_min"), "flood_state": r.get("flood_state"),
        "agent_tool_findings": [f"{s.get('tool')}: {s.get('result_summary')}" for s in (decision or {}).get("steps", [])][:6],
    }


def build_triage(store, now: float | None = None) -> dict[str, Any]:
    idx = store.get_json("live/index.json") or {}
    day = time.strftime("%Y-%m-%d", time.gmtime(now or time.time()))
    decisions = _last_decisions(store, day)
    pending = _pending(store)
    entries, quiet = [], {"night": [], "ok": []}
    for s in idx.get("sites", []):
        cam = s.get("cam_id")
        flags = [f for f in (s.get("flags") or []) if f != "NIGHT"]
        if not flags and not pending.get(cam) and s.get("status") in ("ok", "night", "stale", None):
            quiet["night" if s.get("status") == "night" else "ok"].append(cam)
            continue
        r = store.get_json(f"live/sites/{cam}/latest.json") or s
        meta = store.get_json(f"models/sites/{cam}/meta.json")
        d = decisions.get(cam)
        sev, why = _sev_of(r, d, pending.get(cam, []))
        entries.append({
            "cam_id": cam, "severity": sev, "needs": LABELS[sev], "reason": why, "status": r.get("status"),
            "flags": r.get("flags"), "t_frame": r.get("t_frame"),
            "pending_approvals": _group_pending(pending.get(cam, [])),
            "last_decision": None if not d else {"t_frame": d.get("t_frame"), "decided_by": d.get("decided_by"),
                                                  "model": d.get("model"), "actions": [a.get("type") for a in d.get("actions", [])]},
            "evidence": evidence(r, d), "overlay_key": r.get("overlay_key") or r.get("last_daylight_overlay_key"),
            "_h": _height(r, meta),
        })
    entries.sort(key=lambda e: (-e["severity"], -e["_h"], e["cam_id"]))
    for i, e in enumerate(entries, 1):
        e["rank"] = i
        e.pop("_h")
    return {"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now or time.time())),
            "cycle_started": idx.get("cycle_started"), "n_sites": len(idx.get("sites", [])),
            "n_need_human": sum(e["severity"] >= 3 or bool(e["pending_approvals"]) for e in entries),
            "ranking": "most consequential pending item first (alert > suspect gauge > recalibration/gap-fill > "
                       "quarantine/above range > watching), then river height relative to the site's calibration",
            "ranked": entries, "quiet": quiet}


def write_triage(store) -> dict[str, Any]:
    t = build_triage(store)
    store.put_json("live/agent/triage.json", t)
    return t


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m riversight.agent.triage")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--s3", metavar="BUCKET")
    g.add_argument("--local", metavar="DIR")
    ap.add_argument("--dry-run", action="store_true", help="print, do not write")
    a = ap.parse_args(argv)
    from riversight.live.store import LocalStore, S3Store
    from pathlib import Path
    store = S3Store(a.s3) if a.s3 else LocalStore(Path(a.local))
    t = build_triage(store)
    if not a.dry_run:
        store.put_json("live/agent/triage.json", t)
    print(json.dumps({k: t[k] for k in ("generated_utc", "n_sites", "n_need_human")}, indent=1))
    for e in t["ranked"]:
        print(f"{e['rank']:2d}. [{e['severity']}] {e['cam_id'][:40]:40s} {e['needs']}")


if __name__ == "__main__":
    main()
