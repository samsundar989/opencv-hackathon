"""Build the River Steward fault-injection episode set (INTERFACES §5) — expected actions written here, before
any arm runs. Output: results/agent_eval/episodes.jsonl (+ episodes_summary.csv).

Every episode carries the full agent Event (reading + recent readings + site meta), the tool-context settings the
eval harness applies (protocol-cut bundle, clock, hidden references, injected gauge fault), and the labels:
  expected_actions   actions that must be present
  forbidden_actions  actions that must be absent
  expected_args      e.g. MARK_PROVISIONAL.source
  severity           0–5, for the fleet-triage episodes

Episode kinds (source = what is real):
  real    reg_loss_onset / reg_loss_persist   frames from unlinked history segments that fail registration to the
                                              main reference (camera re-aimed or strong seasonal appearance change),
                                              usable quality; own + later segment references hidden from the bank
  real    reanchor_banked                     frames of linked segments: fail the main reference, match a banked
                                              calibrated reference -> SET_REFERENCE
  real    rise_alert / rise_minor             test-window rises at event sites; alert iff the gauge reaches the
                                              site's calibration p90 within 6 h (hindsight label)
  real    control_view / control_disagree     clean frames with a spurious VIEW_CHANGE / DISAGREE flag -> NOOP
  synth   view_transient (fog, droplets, IR), view_shift (2–8 % homography) -> NOOP
  synth   disagree_camfault (occlusion, fog, droplets) -> QUARANTINE
  synth   stale_camera (gauge dropout 6–72 h, usable frame) -> MARK_PROVISIONAL(camera)
  synth   stale_night (dropout + IR frame) -> MARK_PROVISIONAL(last_known)
  synth   gauge_offset (step of max(0.5 ft, 3σ)), gauge_drift (0.5 ft/day), gauge_flatline (stuck 8–24 h) ->
          OPEN_TICKET gauge_suspect
  fleet   4 flagged sites in one cycle, distinct severities -> rank by severity

Frames used to calibrate tool thresholds (results/agent_eval/tool_calibration.csv) are excluded.

  python scripts/agent_build_episodes.py        (light; reads cached frames, ~2 min)
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
from riversight.agent import faults, tools  # noqa: E402
from riversight.live.quality import image_quality  # noqa: E402
from riversight.agent.store import load_frame  # noqa: E402

DATA = ROOT / "data"
BUNDLES = DATA / "derived" / "agent_bundles"
OUT = ROOT / "results" / "agent_eval"
RNG = np.random.default_rng(20261023)
EXCLUDE = set(pd.read_csv(OUT / "tool_calibration.csv")["filename"]) if (OUT / "tool_calibration.csv").exists() else set()
APPROVAL = ["DRAFT_ALERT", "OPEN_TICKET"]
ALL_BUT_NOOP = ["SET_REFERENCE", "QUARANTINE", "MARK_PROVISIONAL", "OPEN_TICKET", "DRAFT_ALERT"]


# ---- per-site data ----------------------------------------------------------------------------------

class Site:
    def __init__(self, cam: str):
        self.cam = cam
        self.meta = json.loads((BUNDLES / cam / "meta.json").read_text(encoding="utf-8"))
        d = DATA / "derived" / cam
        hf = pd.read_parquet(d / "history" / "frames.parquet")
        hr = pd.read_parquet(d / "history" / "registration.parquet")[["filename", "night", "ok", "n_inliers", "score", "method", "segment"]]
        h = hf.merge(hr, on="filename")
        kf = pd.read_parquet(d / "frames.parquet")
        kr = pd.read_parquet(d / "registration_cascade.parquet")[["filename", "night", "ok", "n_inliers", "score", "method"]]
        k = kf.merge(kr, on="filename").assign(segment="main")
        self.frames = pd.concat([h, k]).drop_duplicates("filename").sort_values("time").reset_index(drop=True)
        self.frames["night"] = self.frames["night"].astype(bool)
        self.frames["ok"] = self.frames["ok"].astype(bool)
        g = tools._history_gauge(cam)
        self.gauge = g
        p = ROOT / "results" / "kill_test_v2" / f"{cam}_pred.csv"
        self.pred = pd.read_csv(p, parse_dates=["time"]).set_index("time") if p.exists() else pd.DataFrame()
        sp = d / "history" / "segments.csv"
        self.segments = pd.read_csv(sp) if sp.exists() else pd.DataFrame()
        self.sigma = float(self.meta.get("sigma_ft") or 0.3)

    def key(self, fn: str) -> str:
        return f"data/raw/720/{self.cam}/{fn}"

    def gauge_at(self, t, fault=None, now=None):
        g = tools.apply_gauge_fault(self.gauge[self.gauge.index <= t], now or t, fault) if fault else self.gauge[self.gauge.index <= t]
        if not len(g):
            return None, None
        return float(g.iloc[-1]), g.index[-1]

    def flood_state(self, h):
        if h is None:
            return None
        return "flood" if h >= self.meta.get("flood_ft", 1e9) else ("elevated" if h >= self.meta.get("flood_elevated_ft", 1e9) else "normal")


def reading(site: Site, row, flags, *, frame_key=None, camera_ft=None, fault=None, now=None, reg_ok=None):
    t = row["time"]
    key = frame_key or site.key(row["filename"])
    gv, gt = site.gauge_at(t, fault, now or t)
    img = load_frame(key)
    q = image_quality(img) if img is not None else {}
    if camera_ft is None and len(site.pred) and t in site.pred.index:
        camera_ft = float(site.pred.loc[t, "camera_ft"])
    return {"cam_id": site.cam, "t_frame": t.isoformat(), "daylight": not bool(row["night"]), "frame_key": key,
            "registration": {"ok": bool(row["ok"] if reg_ok is None else reg_ok), "inliers": int(row["n_inliers"] or 0),
                             "inlier_ratio": round(float(row["score"] or 0), 3), "method": row["method"], "ref": "reference.jpg"},
            "quality": q, "camera_stage_ft": None if camera_ft is None else round(camera_ft, 3),
            "camera_sigma_ft": round(site.sigma, 3), "gauge_stage_ft": gv,
            "gauge_time": gt.isoformat() if gt is not None else None,
            "gauge_age_min": round((t - gt).total_seconds() / 60) if gt is not None else None,
            "flood_state": site.flood_state(gv if gv is not None else camera_ft), "flags": sorted(set(flags))}


def recent(site: Site, t, n=6, fault=None, now=None, flag_fn=None):
    prev = site.frames[(site.frames["time"] < t) & ~site.frames["night"]].iloc[-n:]
    out = []
    for _, r in prev.iterrows():
        fl = flag_fn(r) if flag_fn else ([] if r["ok"] else ["VIEW_CHANGE"])
        rd = reading(site, r, fl, fault=fault, now=now)
        rd.pop("quality", None)
        out.append(rd)
    return out


def site_meta(site):
    return {k: site.meta.get(k) for k in ("cam_id", "nwis_id", "tier", "sigma_ft", "stage_p05", "stage_p50", "stage_p90",
                                          "stage_p95", "stage_min", "stage_max", "flood_elevated_ft", "flood_ft")}


EPISODES: list[dict] = []


def add(kind, source, site, t0, read, rec, expected, forbidden=(), args=None, severity=0, injected=None, ctx=None, note=""):
    eid = f"{kind}-{site.cam[:24]}-{pd.Timestamp(t0).strftime('%Y%m%dT%H%M')}"
    if any(e["episode_id"] == eid for e in EPISODES):
        eid += f"-{len(EPISODES)}"
    EPISODES.append({"episode_id": eid, "kind": kind, "cam_id": site.cam, "source": source, "t0": pd.Timestamp(t0).isoformat(),
                     "injected": injected or {}, "expected_actions": list(expected), "forbidden_actions": list(forbidden),
                     "expected_args": args or {}, "severity": severity, "note": note,
                     "ctx": {"now": pd.Timestamp(t0).isoformat(), "bank_exclude": [], "gauge_fault": None, **(ctx or {})},
                     "event": {"event_id": eid, "cam_id": site.cam, "mode": "eval", "reading": read, "recent": rec,
                               "site_meta": site_meta(site)}})


def usable(site, key) -> bool:
    ctx = tools.ToolContext(mode="eval", bundle_root=BUNDLES, event={"cam_id": site.cam, "reading": {}})
    q = tools.call(ctx, "image_quality", {"frame_key": key})
    return bool(q.get("usable"))


def pick(df, n, seed):
    df = df[~df["filename"].isin(EXCLUDE)]
    return df.sample(min(n, len(df)), random_state=seed) if len(df) else df


# ---- real: registration loss and re-anchoring --------------------------------------------------------

def later_refs(site, t):
    """Reference files of segments that start after t (not knowable at t) — hidden from the bank."""
    return [e["file"] for e in site.meta.get("extra_references", []) if pd.Timestamp(e["start"], tz="UTC") > t]


def build_reg_loss(sites, max_segments=6):
    n = 0
    for site in sites:
        if not len(site.segments):
            continue
        for _, s in site.segments.iterrows():
            if s["linked"] or n >= max_segments:
                continue
            own = [e["file"] for e in site.meta.get("extra_references", []) if e["segment"] == s["segment"]]
            fr = site.frames[(site.frames["segment"] == f"{s['segment']}-unlinked") | (
                (site.frames["time"] >= pd.Timestamp(s["start"], tz="UTC")) &
                (site.frames["time"] < pd.Timestamp(s["end"], tz="UTC") + pd.Timedelta("1D")))]
            fr = fr[~fr["night"] & ~fr["ok"] & ~fr["filename"].isin(EXCLUDE)].sort_values("time")
            fr = fr[[usable(site, site.key(f)) for f in fr["filename"].iloc[:40]] + [False] * max(len(fr) - 40, 0)]
            if len(fr) < 4:
                continue
            for idx in (0, 3):
                r = fr.iloc[idx]
                t = r["time"]
                rec = recent(site, t)
                # label by the persistence the recent readings actually show (previous 2 also failed to register)
                persistent = len(rec) >= 2 and all("VIEW_CHANGE" in x["flags"] for x in rec[-2:])
                exp = ["QUARANTINE", "OPEN_TICKET"] if persistent else ["QUARANTINE"]
                add("reg_loss_persist" if persistent else "reg_loss_onset", "real", site, t,
                    reading(site, r, ["VIEW_CHANGE"]), rec, exp, ["SET_REFERENCE", "DRAFT_ALERT"],
                    severity=3 if persistent else 2, ctx={"bank_exclude": sorted(set(own + later_refs(site, t)))},
                    note=f"{s['segment']} {s['start']}..{s['end']} (main reg ok-rate {s['main_ok_rate']:.2f})")
            n += 1


def build_reanchor(sites, per_segment=2):
    for site in sites:
        if not len(site.segments):
            continue
        for _, s in site.segments[site.segments["linked"].astype(bool)].iterrows():
            ref_file = next((e["file"] for e in site.meta.get("extra_references", []) if e["segment"] == s["segment"]), None)
            if not ref_file or not next(e for e in site.meta["extra_references"] if e["file"] == ref_file).get("linked"):
                continue
            fr = site.frames[(site.frames["segment"] == s["segment"]) & ~site.frames["night"] & (site.frames["filename"] != s["seg_ref"])]
            fr = pick(fr, 8, 7)
            fr = fr[[usable(site, site.key(f)) for f in fr["filename"]]].iloc[:per_segment] if len(fr) else fr
            for _, r in fr.iterrows():
                t = r["time"]
                add("reanchor_banked", "real", site, t, reading(site, r, ["VIEW_CHANGE"], reg_ok=False), recent(site, t),
                    ["SET_REFERENCE"], ["QUARANTINE", "OPEN_TICKET", "DRAFT_ALERT"], args={"SET_REFERENCE": {"ref": ref_file}},
                    severity=2, ctx={"bank_exclude": later_refs(site, t)},
                    note=f"linked {s['segment']} ({s['start']}..{s['end']}), banked ref {ref_file}")


# ---- real: rises and controls (test window, protocol-cut bundles) ------------------------------------

def test_frames(site):
    if not len(site.pred):
        return site.frames.iloc[0:0]
    f = site.frames[site.frames["time"].isin(site.pred.index) & site.frames["ok"] & ~site.frames["night"]]
    return f[~f["filename"].isin(EXCLUDE)]


def change(site, t, hours):
    g = site.gauge
    a = g[g.index <= t]
    b = g[g.index <= t - pd.Timedelta(hours=hours)]
    return float(a.iloc[-1] - b.iloc[-1]) if len(a) and len(b) else 0.0


def build_rises(sites):
    for site in sites:
        f = test_frames(site)
        if not len(f):
            continue
        ch = np.array([change(site, t, 1) for t in f["time"]])
        lvl = np.array([site.gauge_at(t)[0] or np.nan for t in f["time"]])
        p50, p90 = site.meta["stage_p50"], site.meta["stage_p90"]
        crest = np.array([site.gauge[(site.gauge.index >= t) & (site.gauge.index <= t + pd.Timedelta("6h"))].max() for t in f["time"]])
        cand = np.flatnonzero(ch >= 0.10)
        if len(cand):
            i = cand[np.argmax(ch[cand])]
            alert = bool(crest[i] >= p90)
            r = f.iloc[i]
            add("rise_alert" if alert else "rise_minor", "real", site, r["time"], reading(site, r, ["RISING"]), recent(site, r["time"]),
                ["DENSIFY", "DRAFT_ALERT"] if alert else ["DENSIFY"], ["QUARANTINE", "SET_REFERENCE"] + ([] if alert else ["DRAFT_ALERT"]),
                severity=5 if alert else 1,
                note=f"gauge {lvl[i]:.2f} ft, +{ch[i]:.2f} ft/h, 6 h crest {crest[i]:.2f} vs p90 {p90:.2f}")
        minor = np.flatnonzero((ch >= 0.03) & (ch < 0.10) & (lvl < p50) & (crest < p90))
        if len(minor):
            r = f.iloc[minor[len(minor) // 2]]
            add("control_rise", "real", site, r["time"], reading(site, r, ["RISING"]), recent(site, r["time"]),
                [], ["DRAFT_ALERT", "QUARANTINE", "SET_REFERENCE", "OPEN_TICKET"], severity=1,
                note="small rise below the site median; densify allowed, no alert")


def build_controls(sites, n_view=8, n_dis=5):
    ok = [s for s in sites if len(test_frames(s))]
    for j, site in enumerate(RNG.permutation(ok)[:n_view]):
        for _, r in pick(test_frames(site), 1, j).iterrows():
            if not usable(site, site.key(r["filename"])):
                continue
            add("control_view", "real", site, r["time"], reading(site, r, ["VIEW_CHANGE"]), recent(site, r["time"]),
                [], ALL_BUT_NOOP, severity=0, injected={"spurious_flag": "VIEW_CHANGE"},
                note="clean registered frame with a spurious VIEW_CHANGE flag")
    k = 0
    for site in RNG.permutation(ok):
        if k >= n_dis:
            break
        f = test_frames(site)
        good = f[[abs(site.pred.loc[t, "camera_ft"] - site.pred.loc[t, "gauge_ft"]) < 0.5 * site.sigma for t in f["time"]]]
        for _, r in pick(good, 1, 11).iterrows():
            if not usable(site, site.key(r["filename"])):
                continue
            add("control_disagree", "real", site, r["time"], reading(site, r, ["DISAGREE"]), recent(site, r["time"]),
                [], ["QUARANTINE", "OPEN_TICKET", "DRAFT_ALERT", "SET_REFERENCE"], severity=0, injected={"spurious_flag": "DISAGREE"},
                note="camera within 0.5 sigma of the gauge; spurious DISAGREE flag")
            k += 1


# ---- synthetic --------------------------------------------------------------------------------------

def base_frames(sites, n, seed, max_err_sigma=1.0):
    """n (site, row) pairs of clean test-window frames where the frozen camera estimate is within max_err σ."""
    out, sid = [], 0
    pool = [s for s in sites if len(test_frames(s))]
    order = list(RNG.permutation(len(pool)))
    while len(out) < n and sid < 10 * n:
        site = pool[order[sid % len(pool)]]
        sid += 1
        f = test_frames(site)
        f = f[[abs(site.pred.loc[t, "camera_ft"] - site.pred.loc[t, "gauge_ft"]) < max_err_sigma * site.sigma for t in f["time"]]]
        if not len(f):
            continue
        r = f.sample(1, random_state=seed + sid).iloc[0]
        if r["filename"] in {x[1]["filename"] for x in out} or not usable(site, site.key(r["filename"])):
            continue
        out.append((site, r))
    return out


def build_synthetic(sites):
    seed = 100
    # VIEW_CHANGE with transient faults and small bumps -> NOOP
    for fault, n in (("fog", 2), ("droplets", 2), ("ir", 2), ("shift", 3)):
        for site, r in base_frames(sites, n, seed):
            seed += 1
            k = faults.synth_key(fault, seed, site.key(r["filename"]))
            add("view_shift" if fault == "shift" else "view_transient", "synthetic", site, r["time"],
                reading(site, r, ["VIEW_CHANGE"] + (["NIGHT"] if fault == "ir" else []), frame_key=k, reg_ok=False), recent(site, r["time"]),
                ["NOOP"], ALL_BUT_NOOP, severity=0, injected={"frame_fault": fault, "seed": seed})
    # DISAGREE caused by a camera fault -> QUARANTINE
    for fault in ("occlusion", "occlusion", "fog", "droplets"):
        for site, r in base_frames(sites, 1, seed):
            seed += 1
            k = faults.synth_key(fault, seed, site.key(r["filename"]))
            g = site.gauge_at(r["time"])[0]
            add("disagree_camfault", "synthetic", site, r["time"],
                reading(site, r, ["DISAGREE", "LOW_QUALITY"], frame_key=k, camera_ft=g + 3 * site.sigma), recent(site, r["time"]),
                ["QUARANTINE"], ["OPEN_TICKET", "DRAFT_ALERT", "SET_REFERENCE"], severity=2,
                injected={"frame_fault": fault, "seed": seed, "camera_reading": "gauge + 3 sigma"})
    # GAUGE_STALE: dropout on a usable frame -> camera gap-fill; on an IR frame -> last known
    for hours in (6, 12, 24, 48, 72):
        for site, r in base_frames(sites, 1, seed):
            seed += 1
            fault = {"kind": "dropout", "hours": hours}
            add("stale_camera", "synthetic", site, r["time"], reading(site, r, ["GAUGE_STALE"], fault=fault), recent(site, r["time"], fault=fault),
                ["MARK_PROVISIONAL"], ["QUARANTINE", "DRAFT_ALERT", "OPEN_TICKET"], args={"MARK_PROVISIONAL": {"source": "camera"}},
                severity=3, injected={"gauge_fault": fault}, ctx={"gauge_fault": fault})
    for hours in (12, 24, 48):
        for site, r in base_frames(sites, 1, seed):
            seed += 1
            fault = {"kind": "dropout", "hours": hours}
            k = faults.synth_key("ir", seed, site.key(r["filename"]))
            add("stale_night", "synthetic", site, r["time"], reading(site, r, ["GAUGE_STALE", "NIGHT"], frame_key=k, fault=fault),
                recent(site, r["time"], fault=fault), ["MARK_PROVISIONAL"], ["DRAFT_ALERT", "OPEN_TICKET", "SET_REFERENCE"],
                args={"MARK_PROVISIONAL": {"source": "last_known"}}, severity=2,
                injected={"gauge_fault": fault, "frame_fault": "ir", "seed": seed}, ctx={"gauge_fault": fault})
    # gauge faults while the camera is right -> OPEN_TICKET gauge_suspect
    specs = [("gauge_offset", {"kind": "offset", "hours": h}) for h in (1, 2, 3, 2)] + \
            [("gauge_drift", {"kind": "drift", "hours": h, "ft_per_day": 0.5}) for h in (48, 72, 60)] + \
            [("gauge_flatline", {"kind": "flatline", "hours": h}) for h in (8, 16, 24)]
    for kind, spec in specs:
        for site, r in base_frames(sites, 12, seed, max_err_sigma=0.5):      # first candidate where the fault shows
            seed += 1
            fault = dict(spec)
            if kind == "gauge_offset":
                fault = {**fault, "ft": round(max(0.5, 3 * site.sigma), 2)}
            if kind == "gauge_flatline":
                # a stuck sensor only shows when the true river moved since it stuck
                moved = abs(change(site, r["time"], fault["hours"]))
                if moved < 2 * site.sigma:
                    continue
            g_fault = site.gauge_at(r["time"], fault)[0]
            cam = site.pred.loc[r["time"], "camera_ft"]
            if abs(g_fault - cam) < 2 * site.sigma:
                continue                                   # the fault is not visible against this camera
            flag_fn = lambda rr, s=site, f=fault, t0=r["time"]: (["DISAGREE"] if abs((s.gauge_at(rr["time"], f, t0)[0] or 0) - (
                s.pred.loc[rr["time"], "camera_ft"] if rr["time"] in s.pred.index else np.nan)) > 2 * s.sigma else [])
            add(kind, "synthetic", site, r["time"], reading(site, r, ["DISAGREE"], fault=fault),
                recent(site, r["time"], fault=fault, now=r["time"], flag_fn=flag_fn),
                ["OPEN_TICKET"], ["QUARANTINE", "DRAFT_ALERT", "SET_REFERENCE"], args={"OPEN_TICKET": {"kind": "gauge_suspect"}},
                severity=4, injected={"gauge_fault": fault}, ctx={"gauge_fault": fault})
            break


# ---- fleet ------------------------------------------------------------------------------------------

def build_fleet(n=12, size=4):
    pool = [e for e in EPISODES if e["kind"] != "fleet"]
    rng = np.random.default_rng(7)
    fleets, tries = [], 0
    while len(fleets) < n and tries < 2000:
        tries += 1
        members = list(rng.choice(len(pool), size, replace=False))
        eps = [pool[i] for i in members]
        if len({e["cam_id"] for e in eps}) < size or len({e["severity"] for e in eps}) < size:
            continue
        if not any(e["severity"] >= 4 for e in eps):
            continue
        key = tuple(sorted(e["episode_id"] for e in eps))
        if key in {tuple(sorted(f["members"])) for f in fleets}:
            continue
        order = [e["episode_id"] for e in sorted(eps, key=lambda e: -e["severity"])]
        fleets.append({"episode_id": f"fleet-{len(fleets):02d}", "kind": "fleet", "cam_id": "*", "source": "real+synthetic",
                       "t0": None, "injected": {}, "members": [e["episode_id"] for e in eps], "expected_order": order,
                       "expected_actions": [], "forbidden_actions": [], "expected_args": {}, "severity": None,
                       "note": "one cycle with 4 flagged cameras; rank who needs a human first"})
    EPISODES.extend(fleets)


def main():
    sites = [Site(p.name) for p in sorted(BUNDLES.iterdir()) if (p / "meta.json").exists()]
    build_reg_loss(sites)
    build_reanchor(sites)
    build_rises(sites)
    build_controls(sites)
    build_synthetic(sites)
    build_fleet()
    OUT.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e, sort_keys=True, default=str) for e in EPISODES]
    (OUT / "episodes.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summ = pd.DataFrame([{k: e.get(k) for k in ("episode_id", "kind", "cam_id", "source", "t0", "severity")} |
                         {"expected": "+".join(e["expected_actions"]) or "NOOP-ish", "forbidden": "+".join(e["forbidden_actions"]),
                          "note": e.get("note", "")} for e in EPISODES])
    summ.to_csv(OUT / "episodes_summary.csv", index=False)
    single = summ[summ["kind"] != "fleet"]
    print(single.groupby(["source", "kind"]).size().to_string())
    print(f"single-site episodes {len(single)} (real {int((single['source'] == 'real').sum())}), "
          f"clean controls {int(single['kind'].str.startswith('control').sum() + single['kind'].isin(['view_transient', 'view_shift']).sum())}, "
          f"fleet {int((summ['kind'] == 'fleet').sum())}")
    print("sha256", hashlib.sha256((OUT / "episodes.jsonl").read_bytes().replace(b"\r\n", b"\n")).hexdigest())


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()
