"""Scan every served site's gauge history for tides (D-0013 W2-1) → results/agent_eval/tidal_sites.json.

For each camera (the 20 frozen sites + W5's onboarded sites): harmonic fit over 14-day windows (agent/tidal.detect)
and the distribution of daily maxima. The agent reads this file (`tools.site_tidal`); W1 may copy `tidal` into
meta.json. Light (numpy lstsq on hourly data), runs directly.

  python scripts/agent_tidal_scan.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from riversight.agent import tidal, tools  # noqa: E402

OUT = ROOT / "results" / "agent_eval" / "tidal_sites.json"


def cams() -> list[str]:
    out = []
    for root in (ROOT / "models" / "sites", ROOT / "models" / "onboard"):
        if root.exists():
            out += [d.name for d in sorted(root.iterdir()) if (d / "meta.json").exists()]
    return sorted(set(out))


def main():
    res = {}
    for cam in cams():
        g = tools._history_gauge(cam)
        if not len(g):
            res[cam] = {"tidal": False, "note": "no gauge history"}
            continue
        r = tidal.detect(g)
        r.update(tidal.daily_max_quantiles(g))
        if r.get("tidal"):
            r.update(tidal.residual_quantiles(g))
        r["history_days"] = round((g.index[-1] - g.index[0]).total_seconds() / 86400, 1)
        res[cam] = r
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"method": "harmonic fit (M2,S2,K1,O1 + trend), 14-day windows; tidal when >= 60% "
                                         f"of windows explain >= {tidal.TIDAL_R2:.0%} of detrended variance",
                               "sites": res}, indent=1), encoding="utf-8")
    pkg = ROOT / "src" / "riversight" / "agent" / "tidal_sites.json"     # ships with the code to the live worker
    pkg.write_text(json.dumps({c: {k: r.get(k) for k in ("tidal", "median_r2", "median_amplitude_ft", "daily_max_p50",
                                                          "daily_max_p90", "daily_max_p95", "daily_max_p99",
                                                          "resid_p95", "resid_p99")}
                               for c, r in res.items() if r.get("tidal")}, indent=1), encoding="utf-8")
    for cam, r in sorted(res.items(), key=lambda kv: -(kv[1].get("median_r2") or 0))[:12]:
        print(f"{cam[:55]:55s} tidal={r.get('tidal')!s:5s} r2={r.get('median_r2')} amp={r.get('median_amplitude_ft')} "
              f"windows={r.get('windows')}")
    print(f"{sum(r.get('tidal', False) for r in res.values())} tidal of {len(res)} -> {OUT}")


if __name__ == "__main__":
    main()
