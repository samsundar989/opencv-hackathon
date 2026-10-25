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


def prospective() -> str:
    f = RES / "live_prospective" / "summary.json"
    if not f.exists():
        return "_No prospective results committed yet._"
    sm = json.loads(f.read_text(encoding="utf-8"))
    fl = sm["fleet"]
    ps = pd.read_csv(RES / "live_prospective" / "per_site.csv")
    ps = ps[ps.scored > 0].sort_values("scored", ascending=False)
    beats = sm["sites_camera_beats_lkv24"]
    verdict = ("The camera beats a 24-hour-old gauge value at "
               f"{beats} of {sm['sites_scored']} scored sites so far"
               + (". That matches the frozen test: in quiet conditions persistence is hard to beat; the camera's"
                  " value is outages, flood state and QA." if beats == 0 else "."))
    rows = [f"Window: {sm['window_start_utc'][:16].replace('T', ' ')} UTC (first COOL cycle) to "
            f"{sm['scored_until_utc'][:16].replace('T', ' ')} UTC so far; submission cut {sm['submission_cut_utc'][:16].replace('T', ' ')} UTC. "
            f"Models: {sm['models']}. Match: {sm['rules']['match']}. {verdict}", "",
            "| | readings | daylight | scored | saturated (gauge trusted) | coverage | camera MAE ft | median AE ft | within ±0.25 ft | 24 h last-known MAE ft |",
            "|---|---|---|---|---|---|---|---|---|---|",
            f"| **fleet** | {fl['readings']} | {fl['daylight_readings']} | {fl['scored']} | {fl['saturated_gauge_trusted']} | "
            f"{fl['coverage_pct']} % | {fl['mae_ft']} | {fl['median_ae_ft']} | {fl['within_025_pct']} % | {fl['lkv24_mae_ft']} |"]
    for _, r in ps.iterrows():
        rows.append(f"| {short(r.cam_id)} | {int(r.readings)} | {int(r.daylight_readings)} | {int(r.scored)} | "
                    f"{int(r.saturated_gauge_trusted)} | {_f(r.coverage_pct, 1)} % | {_f(r.mae_ft, 3)} | {_f(r.median_ae_ft, 3)} | "
                    f"{_f(r.within_025_pct, 1)} % | {_f(r.lkv24_mae_ft, 3)} |")
    flags = ", ".join(f"{k} {v}" for k, v in fl["flags"].items())
    acts = ", ".join(f"{k} {v}" for k, v in fl["agent_actions"].items())
    rows += ["", f"Flags raised: {flags}. Agent actions: {acts}."]
    if fl.get("shadow_n"):
        rows += ["", f"Model v2 in shadow on the same live frames: median absolute error {fl['shadow_median_ae_ft']} ft vs "
                 f"{fl['v1_median_ae_on_shadow_rows_ft']} ft for v1, the model served at the time, on {fl['shadow_n']} paired readings (§6.11)."]
    return "\n".join(rows)


def fewshot() -> str:
    f = RES / "onboarding" / "fewshot_summary.csv"
    if not f.exists():
        return "_No onboarding results committed yet._"
    d = pd.read_csv(f)
    rows = ["| days of calibration | " + " | ".join(str(int(x)) for x in d.days) + " |",
            "|---" * (len(d) + 1) + "|",
            "| median MAE ft | " + " | ".join(_f(x, 3) for x in d.median_mae) + " |",
            "| median nMAE | " + " | ".join(_f(x, 3) for x in d.median_nmae) + " |",
            f"| P1 sites (of {int(d.sites.iloc[0])}) | " + " | ".join(str(int(x)) for x in d.p1_sites) + " |"]
    return "\n".join(rows)


def agent() -> str:
    f = RES / "agent_eval" / "summary.json"
    if not f.exists():
        return "_No agent evaluation committed yet._"
    sm = json.loads(f.read_text(encoding="utf-8"))
    names = {"rules": "deterministic rules", "sonnet": "LLM agent + OpenCV tools", "haiku": "LLM agent + OpenCV tools",
             "haiku_noev": "LLM agent, flags only (no OpenCV evidence)"}
    rows = ["| arm | model | repeats | task success (min–max) | real / synthetic | false actions on clean controls | "
            "fleet triage top-1 | p50 latency s | est. $ total |", "|---|---|---|---|---|---|---|---|---|"]
    for k in ("rules", "sonnet", "haiku", "haiku_noev"):
        a = sm["arms"].get(k)
        if not a:
            continue
        ts = a["task_success_pct"]
        rows.append(f"| {names[k]} | {a.get('model') or '—'} | {a['repeats']} | {ts['mean']} % ({ts['min']}–{ts['max']}) | "
                    f"{a['task_success_real_pct']} % / {a['task_success_synthetic_pct']} % | "
                    f"{a['false_actions_on_clean_controls_pct']} % | {a['fleet_triage_top1_pct']} % | {a['latency_s']['p50']} | "
                    f"{a['estimated_usd_total']} |")
    e = sm["opencv_evidence_effect"]
    es = sm["episode_set"]
    rows += ["", f"Episodes: {es['single_camera_episodes']} single-camera ({es['real']} real, {es['synthetic_labelled']} synthetic and labelled, "
             f"{es['clean_controls']} clean controls) + {es['fleet_cycles']} fleet cycles; expected actions written before any arm ran; "
             f"set frozen with sha256 (`results/agent_eval/FROZEN.json`). "
             f"OpenCV-evidence effect (same LLM with vs without OpenCV tools, paired): {e['points']:+} points "
             f"(95 % CI {e['ci95_points'][0]} to {e['ci95_points'][1]})."]
    lfl = sm.get("like_for_like_v3")
    if lfl:
        names2 = {"rules": "deterministic rules", "hybrid": "**hybrid: rules act, Sonnet 4.6 advises**",
                  "sonnet": "Sonnet 4.6 agent", "haiku": "Haiku 4.5 agent", "haiku_noev": "Haiku 4.5, flags only"}
        rows += ["", f"Like-for-like, every arm on the same {lfl['arms']['rules']['episodes']} frozen v3 episodes (task success, min–max over repeats):", "",
                 "| arm | task success |", "|---|---|"]
        for k in ("hybrid", "rules", "sonnet", "haiku", "haiku_noev"):
            a = lfl["arms"].get(k)
            if a:
                rows.append(f"| {names2[k]} | {a['task_success_pct']} % ({a['min']}–{a['max']}) |")
    hy, hb = sm["arms"].get("hybrid"), sm.get("hybrid")
    if hy and hb:
        rows += ["", f"Hybrid on the extended v4 set (adds tidal episodes): {hy['task_success_pct']['mean']} % task success, "
                 f"{hy['false_actions_on_clean_controls_pct']} % false actions on clean controls, fleet triage top-1 {hy['fleet_triage_top1_pct']} %, "
                 f"p50 latency {hy['latency_s']['p50']} s, about ${hy['estimated_usd_total']} for the whole run. "
                 f"Sonnet's gauge-drift reviews turned {hb['drift_reviews_turned_into_gauge_ticket']} of {hb['drift_reviews']} drift episodes into a "
                 f"human-approved gauge-suspect ticket; its recorded second opinions agreed with the rules {hb['second_opinion_agreement_pct']} % of the time "
                 f"({hb['second_opinions']} decisions) and never override them."]
    td = sm.get("tidal")
    if td:
        r = td["results_runs"]["rules"]
        rows += ["", f"Tidal sites (v4): ordinary tides correctly not alerted {r['tidal_tide']}; the replayed live false alert suppressed "
                 f"{r['tidal_live_false_alert']}; record-high (king-tide) days alerted {r['tidal_flood']}."]
    return "\n".join(rows)


def model_v2() -> str:
    f = RES / "v2" / "cv_summary.csv"
    if not f.exists():
        return "_No model v2 results committed yet._"
    d = pd.read_csv(f).set_index("config")
    v1 = d.loc["v1"]
    sel = d[d.selected.astype(bool)].iloc[0]
    name = d[d.selected.astype(bool)].index[0]
    rows = ["| year-long forward-chaining CV, 20 sites | v1 (D-0007) | v2 selected (`" + name + "`) |", "|---|---|---|",
            f"| median MAE ft | {_f(v1.median_mae, 3)} | **{_f(sel.median_mae, 3)}** ({100 * sel.rel_change:+.1f} %) |",
            f"| mean MAE ft | {_f(v1.mean_mae, 3)} | {_f(sel.mean_mae, 3)} |",
            f"| median nMAE | {_f(v1.median_nmae, 3)} | {_f(sel.median_nmae, 3)} |",
            f"| sites meeting P1 | {int(v1.p1_sites)}/20 | {int(sel.p1_sites)}/20 |",
            f"| sites improved | — | {int(sel.sites_better)}/20 (worst site {sel.worst_site_delta:+.3f} ft) |"]
    return "\n".join(rows)


def fusion() -> str:
    f = RES / "v2" / "fusion_summary.csv"
    if not f.exists():
        return "_No fusion results committed yet._"
    d = pd.read_csv(f)
    rows = ["| outage | last-known gauge | fused (primary, with bias) | fused | camera only | primary beats last-known | fused, river moving vs last-known moving |",
            "|---|---|---|---|---|---|---|"]
    for gap in ("6h", "24h", "72h", "7d"):
        g = d[(d.model == "v1") & (d.gap == gap)].set_index("method")
        rows.append(f"| {gap} | {_f(g.loc['lkv'].median_site_mae, 3)} | **{_f(g.loc['fused_bias'].median_site_mae, 3)}** | "
                    f"{_f(g.loc['fused'].median_site_mae, 3)} | {_f(g.loc['camera'].median_site_mae, 3)} | "
                    f"{int(g.loc['fused_bias'].sites_beating_lkv)}/{int(g.loc['fused_bias'].sites)} sites | "
                    f"{_f(g.loc['fused'].median_site_mae_moving, 2)} vs {_f(g.loc['lkv'].median_site_mae_moving, 2)} |")
    v2 = d[(d.model == "v2") & (d.method == "fused_bias")].set_index("gap")
    rows += ["", "With the v2 candidate camera, the primary fused estimate is " + " / ".join(
        f"{_f(v2.loc[g].median_site_mae, 3)}" for g in ("6h", "24h", "72h", "7d")) + " ft for 6 h / 24 h / 72 h / 7 d outages."]
    return "\n".join(rows)


def recal() -> str:
    f = RES / "v2" / "recal_summary.csv"
    if not f.exists():
        return "_No recalibration results committed yet._"
    d = pd.read_csv(f).set_index(["model", "method"])
    rows = ["| refit schedule | v1 median MAE ft | v2 median MAE ft | MAE on frames above the static calibration range (v1 / v2) |",
            "|---|---|---|---|"]
    for m in ("static", "monthly", "weekly"):
        a, b = d.loc[("v1", m)], d.loc[("v2", m)]
        rows.append(f"| {m} | {_f(a.median_mae, 3)} | {_f(b.median_mae, 3)} | {_f(a.median_mae_above_static_range, 2)} / {_f(b.median_mae_above_static_range, 2)} |")
    return "\n".join(rows)


def shadow() -> str:
    f = RES / "v2" / "shadow_decision.json"
    if not f.exists():
        return "_No shadow decision data committed yet._"
    d = json.loads(f.read_text(encoding="utf-8"))
    return (f"Live shadow, pre-registered (D-0010 §2): on {d['pairs']} paired daylight readings at {d['sites']} sites, v2's median absolute error was "
            f"**{d['v2_median_ae_ft']} ft vs {d['v1_median_ae_ft']} ft** for v1, the model served at the time (difference {d['diff_v2_minus_v1_ft']} ft, site-bootstrap 95 % CI "
            f"{d['diff_site_bootstrap_95ci'][0]} to {d['diff_site_bootstrap_95ci'][1]}); v2 was better at {d['sites_v2_better']} of {d['sites']} sites. "
            f"Caveat: one calm day (median gauge range per site {d['median_gauge_range_ft_per_site']} ft).")


TABLES = {"headline": headline, "per_site": per_site, "baselines": baselines, "ablations": ablations, "hancock": hancock, "registration": registration, "prospective": prospective, "fewshot": fewshot, "agent": agent, "model_v2": model_v2, "fusion": fusion, "recal": recal, "shadow": shadow}


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
