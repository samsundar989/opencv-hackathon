"""Regenerate the tables in report/REPORT.md from committed results (no hand-copied numbers).

Each table lives between `<!-- BEGIN:<name> -->` and `<!-- END:<name> -->`; everything else in the report
is left alone. Run after any results change, then `python scripts/check_report_numbers.py`.

    python report/build_report_tables.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
REPORT = ROOT / "report" / "REPORT.md"


def _f(x, nd=2) -> str:
    return "—" if pd.isna(x) else f"{x:.{nd}f}"


def short(cam: str) -> str:
    st, rest = cam.split("_", 1)
    return f"{rest.replace('_', ' ')} ({st})"


def per_site() -> str:
    kt = pd.read_csv(RES / "kill_test_v2.csv").set_index("cam_id")
    ci = pd.read_csv(RES / "kill_test_v2_ci.csv").set_index("cam_id")
    cov = pd.read_csv(RES / "coverage_v2.csv").set_index("cam_id")
    rows = ["| site | tier | frames | MAE ft [95% CI] | RMSE ft | nMAE | P1 | event MAE: camera / 24 h LKV | daylight hours covered |",
            "|---|---|---|---|---|---|---|---|---|"]
    for cam in kt.index:
        k, c, v = kt.loc[cam], ci.loc[cam], cov.loc[cam]
        ev = f"{_f(k.mae_ev)} / {_f(k.mae_p24_ev)}" if k.n_ev >= 3 else "—"
        rows.append(f"| {short(cam)} | {k.tier} | {int(k.n)} | {_f(c.mae, 3)} [{_f(c.mae_lo, 3)}–{_f(c.mae_hi, 3)}] | "
                    f"{_f(c.rmse, 3)} | {_f(k.nmae)} | {'✔' if k.p1 else '✘'} | {ev} | {_f(v.pct_daylight_hours, 1)} % |")
    return "\n".join(rows)


def baselines() -> str:
    s = json.loads((RES / "kill_test_v2_summary.json").read_text(encoding="utf-8"))
    n = s["n_sites"]
    rows = ["| comparison (all scored frames unless noted) | camera better at |", "|---|---|",
            f"| constant (calibration median) | {s['sites_beat_const']}/{n} |",
            f"| gauge 24 h stale (persistence) | {s['sites_beat_persist_24h']}/{n} |",
            f"| gauge 15 min stale (persistence) | {s['sites_beat_persist_15min']}/{n} |",
            f"| event frames (\\|Δ24h\\| ≥ 0.25 ft): gauge 24 h stale, P2 | {s['p2_sites']}/{s['p2_event_sites']} event sites |"]
    for h, lab in (("6h", "6 h"), ("24h", "24 h"), ("72h", "72 h"), ("7d", "7 days")):
        rows.append(f"| gauge outage of {lab}: last-known value | {s[f'gapfill_sites_beat_lkv_{h}']}/{n} |")
    return "\n".join(rows)


def headline() -> str:
    s = json.loads((RES / "kill_test_v2_summary.json").read_text(encoding="utf-8"))
    c = json.loads((RES / "kill_test_v2_ci_summary.json").read_text(encoding="utf-8"))
    r = s["registration"]
    return "\n".join([
        "| metric | value | source |", "|---|---|---|",
        f"| P1 accuracy (MAE ≤ 0.25 ft or nMAE ≤ 10 %) | **{s['p1_sites']}/{s['n_sites']}** sites "
        f"(bootstrap 95 % interval {c['p1_sites_ci95'][0]}–{c['p1_sites_ci95'][1]}) | `kill_test_v2_verdict.json`, `kill_test_v2_ci_summary.json` |",
        f"| median MAE across sites | **{s['median_mae_ft']} ft** (95 % CI {c['median_mae_ci95_ft'][0]}–{c['median_mae_ci95_ft'][1]}) | `kill_test_v2_ci_summary.json` |",
        f"| median nMAE / Spearman ρ | {s['median_nmae']} / {s['median_spearman']} | `kill_test_v2_summary.json` |",
        f"| P2 value on event frames vs 24 h-stale gauge | **{s['p2_sites']}/{s['p2_event_sites']}** event sites | `kill_test_v2_verdict.json` |",
        f"| P3 registration, 30-day daylight frames | **{100 * r['rate']:.1f} %** ({r['registered']} of {r['day_frames']}) | `kill_test/registration_summary.csv` |",
        f"| flood-state balanced accuracy, median over {s['flood_sites']} sites with flood frames | **{s['flood_bacc_cam_median']}** vs {s['flood_bacc_persist24_median']} (24 h-stale gauge) | `kill_test_v2_summary.json` |",
        f"| coverage: daylight hours with a reading, median site | {c['coverage']['median_pct_daylight_hours']} % ({c['coverage']['median_pct_hours']} % of all hours) | `coverage_v2.csv` |",
        f"| fleet camera-hours of stage per day | {c['coverage']['fleet_camera_hours_per_day']} | `kill_test_v2_ci_summary.json` |",
    ])


def ablations() -> str:
    s = json.loads((RES / "kill_test_v2_summary.json").read_text(encoding="utf-8"))
    r, fw, cv = s["registration"], s["fit_window"], s["year_cv"]
    return "\n".join([
        "| ablation | result | source |", "|---|---|---|",
        f"| registration: ORB + MAGSAC alone vs full cascade | {100 * r['orb_rate']:.1f} % vs {100 * r['rate']:.1f} % of "
        f"{r['day_frames']} daylight frames; ALIKED + LightGlue recovered {r['aliked_lightglue']} frames | `kill_test/registration_summary.csv` |",
        f"| estimator: classical transect waterline vs scene model, 20-day fit-window CV, sites ≤ 0.25 ft | "
        f"{fw['transect_sites_le_025']}/{fw['transect_sites']} vs {fw['scene_sites_le_025']}/{fw['scene_sites']} "
        f"(scene median {fw['scene_median_mae_ft']} ft) | `kill_test/fit_window_cv.csv`, `scene/gate_fit20.csv` |",
        f"| calibration horizon: year-long forward-chaining CV (frozen setting) | P1 at {cv['p1_sites']}/20, median MAE {cv['median_mae_ft']} ft, "
        f"median nMAE {cv['median_nmae']}; {cv['settings_tried']} settings tried | `scene/tune_cv_summary.csv` |",
    ])


def hancock() -> str:
    m = pd.read_csv(RES / "headtohead_hancock" / "metrics.csv").set_index("event")
    ss = json.loads((RES / "headtohead_hancock" / "stagesight_reported.json").read_text(encoding="utf-8"))
    rows = ["| | 29–30 Jul 2026 flood | 4–5 Sep 2026 |", "|---|---|---|"]
    j, sp = m.loc["jul29"], m.loc["sep04"]
    rows += [
        f"| gauge range in window, ft | {_f(j.gauge_min_ft)}–{_f(j.gauge_max_ft)} | {_f(sp.gauge_min_ft)}–{_f(sp.gauge_max_ft)} |",
        f"| our calibration max after leaving the event out, ft | {_f(j.cal_max_ft)} | {_f(sp.cal_max_ft)} |",
        f"| **RiverSight RMSE, ft [95 % CI]** | {_f(j.rmse)} [{_f(j.rmse_lo)}–{_f(j.rmse_hi)}] | {_f(sp.rmse)} [{_f(sp.rmse_lo)}–{_f(sp.rmse_hi)}] |",
        f"| RiverSight MAE / within 0.5 ft | {_f(j.mae)} / {100 * j.within_0p5ft:.1f} % | {_f(sp.mae)} / {100 * sp.within_0p5ft:.1f} % |",
        f"| RiverSight flood-state recall (camera above calibration p90 when the gauge is) | {_f(j.flood_state_recall)} | {_f(sp.flood_state_recall)} |",
        f"| baseline: gauge value at window start held (outage at event start), RMSE | {_f(j.rmse_gauge_held_from_start)} | {_f(sp.rmse_gauge_held_from_start)} |",
        f"| baseline: calibration median, RMSE | {_f(j.rmse_const_median)} | {_f(sp.rmse_const_median)} |",
        f"| RiverSight coverage: hours of the window / listed daylight frames with a reading | {_f(j.cov_pct_hours, 1)} % / {_f(j.cov_pct_listed_daylight, 1)} % | {_f(sp.cov_pct_hours, 1)} % / {_f(sp.cov_pct_listed_daylight, 1)} % |",
        f"| StageSight RMSE as reported, ft (not reproduced by us) | {ss['jul29_rmse_ft']} [{ss['jul29_rmse_ci95_ft'][0]:.2f}–{ss['jul29_rmse_ci95_ft'][1]:.2f}] | {ss['sep04_rmse_ft']} |",
        f"| StageSight coverage as reported | {ss['coverage_pct_hourly_frames']} % of hourly frames (whole archive) | |",
    ]
    return "\n".join(rows)


def registration() -> str:
    a = pd.read_csv(RES / "registration_ablation.csv").set_index("cam_id")
    sm = json.loads((RES / "registration_ablation_summary.json").read_text(encoding="utf-8"))
    pc = lambda v: "—" if pd.isna(v) else f"{100 * v:.1f} %"  # noqa: E731
    rows = ["| site | 30 d: ORB | + ALIKED+LightGlue | + chaining | 12 mo: main reference | + reference bank | usable for calibration |",
            "|---|---|---|---|---|---|---|"]
    for cam, r in a.iterrows():
        rows.append(f"| {short(cam)} | {pc(r.orb_rate_30d)} | {pc(r.orb_aliked_rate_30d)} | {pc(r.cascade_rate_30d)} | "
                    f"{pc(r.get('hist_main_only_rate'))} | {pc(r.get('hist_with_bank_rate'))} | {pc(r.get('hist_usable_rate'))} |")
    w, h = sm["window_30d"], sm.get("history_12m", {})
    rows.append(f"| **fleet** ({w['day_frames']} / {h.get('day_frames', '—')} daylight frames) | **{pc(w['orb_rate'])}** | "
                f"**{pc(w['orb_aliked_rate'])}** | **{pc(w['cascade_rate'])}** | **{pc(h.get('main_only_rate'))}** | "
                f"**{pc(h.get('with_bank_rate'))}** | **{pc(h.get('usable_rate'))}** |")
    return "\n".join(rows)


TABLES = {"headline": headline, "per_site": per_site, "baselines": baselines, "ablations": ablations, "hancock": hancock, "registration": registration}


def main() -> None:
    txt = REPORT.read_text(encoding="utf-8")
    for name, fn in TABLES.items():
        pat = re.compile(rf"(<!-- BEGIN:{name} -->\n)(?:.*?\n)?(<!-- END:{name} -->)", re.S)
        if not pat.search(txt):
            raise SystemExit(f"marker for {name} missing in {REPORT}")
        txt = pat.sub(lambda m: m.group(1) + fn() + "\n" + m.group(2), txt)
    REPORT.write_text(txt, encoding="utf-8")
    print(f"updated {len(TABLES)} tables in {REPORT}")


if __name__ == "__main__":
    main()
