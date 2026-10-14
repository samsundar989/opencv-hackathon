"""SLICE_01 kill test runner: every site in the YAML → results/kill_test/{summary.csv, <cam>/...}, kill_test.md.

Heavy-ish (tens of thousands of frames): submit through worker-q (D-0005), e.g.
  workerq submit --project riversight --priority low --ram 4 --cpus 4 --describe "S01 kill test" \
      -- python scripts/kill_test.py --jobs 4

  python scripts/kill_test.py --only CAM_ID      (develop on one site; fit-window numbers only matter)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from riversight.killtest import Cfg, register_site, run_site  # noqa: E402

RES = ROOT / "results" / "kill_test"
MAE_PASS, MIN_SITES, REG_PASS = 0.25, 10, 0.90


def _one(cam: str, t0, ts, t1, score_test: bool = True, register_only: bool = False):
    import cv2
    cv2.setNumThreads(1)
    try:
        if register_only:
            frames, _, _, _, reg = register_site(cam, ROOT / "data", t0, ts, t1, Cfg())
            day = reg[reg["night"] == False]  # noqa: E712
            return cam, {"n_day": len(day), "reg_rate": float(day["ok"].mean()) if len(day) else float("nan"),
                         "methods": day.loc[day["ok"], "method"].value_counts().to_dict()}, [], None
        r = run_site(cam, ROOT / "data", RES / cam, t0, ts, t1, Cfg(), score_test=score_test)
        return cam, r.metrics, r.notes, None
    except Exception:
        return cam, {}, [], traceback.format_exc()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", type=Path, default=ROOT / "data" / "sites" / "kill_test.yaml")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--dev", action="store_true", help="fit-window CV only; never score the test days")
    ap.add_argument("--register-only", action="store_true", help="only the (expensive, cached) registration pass")
    a = ap.parse_args()
    doc = yaml.safe_load(a.sites.read_text(encoding="utf-8"))
    w = doc["window"]
    t1 = pd.Timestamp(w["end"])
    t0 = t1 - pd.Timedelta(days=w["days"])
    ts = t0 + pd.Timedelta(days=w["fit_days"])
    cams = [s["cam_id"] for s in doc["sites"] if not a.only or s["cam_id"] in a.only]
    rows, prog = [], os.environ.get("WORKERQ_PROGRESS")
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(_one, c, t0, ts, t1, not a.dev, a.register_only) for c in cams]
        for k, f in enumerate(as_completed(futs), 1):
            cam, m, notes, err = f.result()
            if err:
                print(f"[FAIL] {cam}\n{err}", flush=True)
                m = {"error": err.strip().splitlines()[-1]}
            else:
                head = (f"registration {m}" if a.register_only else
                        f"CV MAE {m.get('cv_mae_ft')} cv-cov {m.get('cv_coverage')}" if a.dev else
                        f"MAE {m.get('MAE_ft')} cov {m.get('coverage')} CV {m.get('cv_mae_ft')}")
                print(f"[done] {cam}: {head} reg {m.get('reg_rate')} | "
                      + "; ".join(notes), flush=True)
            rows.append({"site": cam, **m, "notes": " | ".join(notes)})
            if prog:
                Path(prog).write_text(f"{k / len(cams):.3f}")
    if a.only or a.dev or a.register_only:
        return
    S = pd.DataFrame(rows).sort_values("site")
    S.to_csv(RES / "summary.csv", index=False)
    md = write_report(S, doc)
    (RES.parent / "kill_test.md").write_text(md + "\n", encoding="utf-8")
    print(md.split("## Registration cascade")[0])


def failure_mode(r: dict) -> str:
    """Coarse, rule-based label for why a site misses (documented in the report legend)."""
    if r.get("error"):
        return "pipeline error"
    if not (r.get("reg_rate", 0) >= 0.8):
        return "registration"
    if not np.isfinite(r.get("MAE_ft", np.nan)):
        return "no usable transect (no stage-correlated band / no valid fit)"
    if r.get("px_per_ft", 0) < 3:
        return "low px/ft (wide river or far bank)"
    if r.get("coverage", 0) < 0.5:
        return "low coverage (detector confidence)"
    if r["MAE_ft"] > MAE_PASS:
        return "detector picks wrong edge / model drift"
    if not r.get("beats_persist", False):
        return "flat test window (persistence already good)"
    return ""


def write_report(S: pd.DataFrame, doc: dict) -> str:
    day = S["n_day"].fillna(0)
    reg_all = float(S["n_day_registered"].fillna(0).sum() / max(day.sum(), 1))
    S = S.copy()
    S["beats_persist"] = S["MAE_ft"] < S["MAE_persist24_ft"]
    S["site_pass"] = (S["MAE_ft"] <= MAE_PASS) & S["beats_persist"]
    S["failure_mode"] = [failure_mode(r) for r in S.to_dict("records")]
    n_mae = int((S["MAE_ft"] <= MAE_PASS).sum())
    n_pass = int(S["site_pass"].sum())
    n_pass_cov = int((S["site_pass"] & (S["coverage"] >= 0.5)).sum())
    verdict = "PASS" if (reg_all >= REG_PASS and n_pass >= MIN_SITES) else "FAIL"
    L = [f"# SLICE_01 kill test — {verdict}", "",
         f"Window: {doc['window']['days']} days ending {doc['window']['end']}; fit = first "
         f"{doc['window']['fit_days']} days, test = last {doc['window']['test_days']} days (scored once).",
         "Pipeline: ORB + USAC_MAGSAC registration → automatic transects from the stage-correlation map → classical "
         "boundary detector → projective u(h) per transect → weighted-median fusion. All selection on the fit window.",
         "Produced by `scripts/kill_test.py` from `data/sites/kill_test.yaml`; numbers below are copied from "
         "`results/kill_test/summary.csv`.", "",
         "## Acceptance", "",
         f"| criterion | required | measured | |", "|---|---|---|---|",
         f"| registration success (daytime frames, all sites) | ≥ 90% | {reg_all:.1%} | {'✅' if reg_all >= REG_PASS else '❌'} |",
         f"| sites with test MAE ≤ 0.25 ft | ≥ 10 / 20 | {n_mae} | {'✅' if n_mae >= MIN_SITES else '❌'} |",
         f"| …of those, also beating persistence-24h | ≥ 10 / 20 | {n_pass} | {'✅' if n_pass >= MIN_SITES else '❌'} |",
         f"| (stricter, informational) …and coverage ≥ 50% | — | {n_pass_cov} | |", "",
         "## Per-site results (test window, daytime frames)", "",
         "| site | day frames | reg | coverage | MAE ft | RMSE | ≤0.1 | ≤0.25 | persist-24h MAE | isotonic MAE | px/ft | test range ft | pass |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    f = lambda v, p=3: "—" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{v:.{p}f}"
    for r in S.to_dict("records"):
        nd = r.get("n_day")
        L.append(f"| {r['site']} | {int(nd) if pd.notna(nd) else '—'} | {f(r.get('reg_rate'), 2)} | "
                 f"{f(r.get('coverage'), 2)} | {f(r.get('MAE_ft'))} | {f(r.get('RMSE_ft'))} | "
                 f"{f(r.get('pct_within_0.1'), 0)}% | {f(r.get('pct_within_0.25'), 0)}% | "
                 f"{f(r.get('MAE_persist24_ft'))} | {f(r.get('MAE_isotonic_ft'))} | {f(r.get('px_per_ft'), 1)} | "
                 f"{f(r.get('test_stage_range_ft'), 2)} | {'✅' if r['site_pass'] else '❌'} |")
    tot = {k: int(S[k].fillna(0).sum()) for k in ("n_reg_orb", "n_reg_aliked", "n_reg_chain") if k in S}
    L += ["", "## Registration cascade", "",
          f"Daytime frames registered by ORB+MAGSAC: {tot.get('n_reg_orb', 0)}; rescued by ALIKED+LightGlue+MAGSAC "
          f"(OpenCV 5): {tot.get('n_reg_aliked', 0)}; rescued by chaining through the previous good frame: "
          f"{tot.get('n_reg_chain', 0)}. Night (IR/dark) frames are excluded and counted separately "
          f"({int(S['n_night'].fillna(0).sum())} frames).",
          "", "## Failure modes (rule-based labels; see `failure_mode()` in `scripts/kill_test.py`)", ""]
    for r in S.to_dict("records"):
        if r["failure_mode"]:
            L.append(f"- **{r['site']}** — {r['failure_mode']}. {r.get('notes', '')}")
    L += ["", "## Overlays", "",
          "Per site: `corrmap.jpg` (reference frame with auto transects | stage-correlation map), `timeseries.png` "
          "(gauge vs camera, fit and test), `overlay_1/2.jpg` (test frames at the highest/lowest test-window stage; "
          "chosen transects yellow, detected waterline red).", ""]
    for r in S.to_dict("records"):
        site = r["site"]
        if (RES / site / "timeseries.png").exists():
            L += [f"### {site}", "", f"![](kill_test/{site}/timeseries.png)", "",
                  f"![](kill_test/{site}/overlay_1.jpg) ![](kill_test/{site}/overlay_2.jpg)", ""]
    return "\n".join(L)


if __name__ == "__main__":
    main()
