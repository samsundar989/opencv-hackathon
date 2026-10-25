"""River Steward episode set v5 (D-0014 / D-0015; built by W5): king-tide advisories and RECALIBRATE.

Expected actions are written here, before any arm runs on them. The 108 single-site + 12 fleet v4 episodes are
loaded from results/agent_eval/episodes.jsonl and kept byte-identical; v5 episodes are appended.

  real   king_tide          a rising, ordinary-height tide (gauge < daily-max p90 at the frame) 6–24 h before the
                            day's high water reached the site's daily-max p99 -> TIDE_ADVISORY (hindsight label from
                            the gauge record, independent of the harmonic model the agent uses); no DRAFT_ALERT
  real   king_tide_control  a rising ordinary tide whose next 24 h stayed below the daily-max p95 -> no TIDE_ADVISORY
  synth  recal_drift        a v4 control_disagree episode + W4 drift signal firing + a refit built on the served
                            model -> RECALIBRATE (plus the base episode's own labels)
  synth  recal_flood        a v4 oor_gauge episode + a refit whose calibrated max rose (the flood) -> RECALIBRATE
  synth  recal_no_bundle    drift firing but no refit bundle                 -> no RECALIBRATE
  synth  recal_wrong_parent refit built on another model than the served one -> no RECALIBRATE
  synth  recal_quiet        refit available, no drift, range unchanged       -> no RECALIBRATE

  python scripts/agent_build_episodes_v5.py        (light; reads cached frames and gauge history)
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import agent_build_episodes as b  # noqa: E402

OUT = ROOT / "results" / "agent_eval"
TIDAL = (("CA_First_Mallard_Branch_nr_Fairfield", b.BUNDLES), ("GA_Savannah_River_at_USACE_Dock_at_Savannah", b.ONBOARD))
NO_FLOOD = ["DRAFT_ALERT", "OPEN_TICKET", "QUARANTINE", "SET_REFERENCE"]
FIT_DAYS = 15          # the agent's forecast needs this much gauge history before the frame


def build_king_tides(n_control=3):
    tid = json.loads((ROOT / "src" / "riversight" / "agent" / "tidal_sites.json").read_text(encoding="utf-8"))
    for cam, root in TIDAL:
        site, dm = b.Site(cam, root), tid[cam]
        g = site.gauge.dropna()
        f = site.frames[~site.frames["night"] & site.frames["ok"] & ~site.frames["filename"].isin(b.EXCLUDE)]
        f = f[f["time"] >= g.index[0] + pd.Timedelta(days=FIT_DAYS)]
        lvl = np.array([site.gauge_at(t)[0] if site.gauge_at(t)[0] is not None else np.nan for t in f["time"]])
        nxt = np.array([g[(g.index > t) & (g.index <= t + pd.Timedelta(hours=24))].max() for t in f["time"]])
        rising = np.array([b.tidal_rising_flag(site, t) for t in f["time"]], bool)
        f = f.assign(level=lvl, next24_max=nxt)
        rel = site.bundles.relative_to(ROOT).as_posix()
        # king days: observed daily max >= p99; one episode per king day, frame nearest 12 h before the peak
        daymax = g.resample("1D").max()
        for day in daymax[daymax >= dm["daily_max_p99"]].index:
            gd = g[(g.index >= day) & (g.index < day + pd.Timedelta("1D"))]
            tp = gd.idxmax()
            cand = f[rising & (f["time"] >= tp - pd.Timedelta(hours=24)).to_numpy() & (f["time"] <= tp - pd.Timedelta(hours=6)).to_numpy()
                     & (f["level"] < dm["daily_max_p90"]).to_numpy()]
            if not len(cand):
                continue
            r = cand.iloc[int(np.argmin(np.abs((cand["time"] - (tp - pd.Timedelta(hours=12))).dt.total_seconds())))]
            b.add("king_tide", "real", site, r["time"], b.reading(site, r, ["RISING"]), b.recent(site, r["time"]),
                  ["TIDE_ADVISORY"], NO_FLOOD, severity=2, ctx={"bundle_root": rel},
                  note=f"hindsight: high water {gd.max():.2f} ft at {tp:%Y-%m-%d %H:%M}Z >= daily-max p99 {dm['daily_max_p99']}; "
                       f"gauge {r['level']:.2f} ft at the frame (< p90 {dm['daily_max_p90']})")
        ctrl = f[rising & (f["level"] < dm["daily_max_p90"]).to_numpy() & (f["next24_max"] < dm["daily_max_p95"]).to_numpy()]
        for _, r in b.pick(ctrl, n_control, 5).iterrows():
            b.add("king_tide_control", "real", site, r["time"], b.reading(site, r, ["RISING"]), b.recent(site, r["time"]),
                  [], NO_FLOOD + ["TIDE_ADVISORY"], severity=0, ctx={"bundle_root": rel},
                  note=f"ordinary tide: next-24 h high water {r['next24_max']:.2f} ft < daily-max p95 {dm['daily_max_p95']}")


SERVED, REFIT = "sha_served_synthetic", "sha_refit_synthetic"
DRIFT_ON = {"n": 42, "window_days": 7, "sigma_ft": 0.25, "median_residual_ft": 0.41, "median_abs_residual_ft": 0.44, "drifting": True}
DRIFT_OFF = dict(DRIFT_ON, median_residual_ft=0.03, median_abs_residual_ft=0.12, drifting=False)


def refit(parent=SERVED, before=5.0, after=5.0):
    return {"model_sha": REFIT, "parent_model_sha": parent, "n_new_frames": 160, "new_from": "2026-10-17",
            "new_to": "2026-10-24", "stage_max_before_ft": before, "stage_max_after_ft": after}


VARIANTS = {   # kind: (base kind, drift, refit meta, RECALIBRATE expected?)
    "recal_drift": ("control_disagree", DRIFT_ON, refit(), True),
    "recal_flood": ("oor_gauge", DRIFT_OFF, refit(before=11.97, after=18.08), True),
    "recal_no_bundle": ("control_disagree", DRIFT_ON, None, False),
    "recal_wrong_parent": ("control_disagree", DRIFT_ON, refit(parent="sha_older_model"), False),
    "recal_quiet": ("control_disagree", DRIFT_OFF, refit(), False),
}


def build_recal(v4: list[dict], per_variant=2):
    for kind, (base_kind, drift, meta, want) in VARIANTS.items():
        bases = sorted((e for e in v4 if e["kind"] == base_kind), key=lambda e: e["episode_id"])[:per_variant]
        for e in bases:
            ep = json.loads(json.dumps(e))
            eid = f"{kind}-{e['episode_id']}"
            ep.update(episode_id=eid, kind=kind, source="synthetic",
                      injected={**e.get("injected", {}), "recal": {"drift": drift, "recal_meta": meta}},
                      note=f"{e.get('note', '')} | injected W4 recal evidence ({kind}); base {e['episode_id']}".strip(" |"))
            ep["event"]["event_id"] = eid
            ep["event"]["reading"]["model_sha"] = SERVED
            ep["ctx"]["recal_inline"] = {"drift": drift, "recal_meta": meta}
            if want:
                ep["expected_actions"] = sorted(set(ep["expected_actions"]) | {"RECALIBRATE"})
                ep["forbidden_actions"] = [a for a in ep["forbidden_actions"] if a != "RECALIBRATE"]
            else:
                ep["forbidden_actions"] = sorted(set(ep["forbidden_actions"]) | {"RECALIBRATE"})
            b.EPISODES.append(ep)


def main():
    path = OUT / "episodes.jsonl"
    v4_lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    v4 = [json.loads(ln) for ln in v4_lines]
    if any(e["kind"].startswith(("king_tide", "recal_")) for e in v4):
        sys.exit("episodes.jsonl already contains v5 episodes; rebuild v4 first (scripts/agent_build_episodes.py)")
    b.EPISODES.extend(v4)
    build_king_tides()
    build_recal(v4)
    new = b.EPISODES[len(v4):]
    lines = v4_lines + [json.dumps(e, sort_keys=True, default=str) for e in new]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summ = pd.DataFrame([{k: e.get(k) for k in ("episode_id", "kind", "cam_id", "source", "t0", "severity")} |
                         {"expected": "+".join(e["expected_actions"]) or "NOOP-ish", "forbidden": "+".join(e["forbidden_actions"]),
                          "note": e.get("note", "")} for e in b.EPISODES])
    summ.to_csv(OUT / "episodes_summary.csv", index=False)
    print(pd.DataFrame(new).groupby(["source", "kind"]).size().to_string())
    print(f"v4 episodes kept byte-identical: {len(v4_lines)}; v5 added {len(new)}; total {len(lines)}")
    print("sha256", hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest())


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()
