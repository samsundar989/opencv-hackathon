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

v2 (2026-10-23): every real view episode is checked against exactly the bank it exposes (`bank_match`, the same
deterministic registration cascade as the agent's tool). v1 trusted the history pipeline's registration flags and
mislabelled 3 episodes (2 Salt Creek frames that match an earlier calibrated reference, 1 Mallard frame that
registers to the main reference); the rules run exposed them. v1 + its rules run are kept in runs_v1/.

v3 (2026-10-23, D-0009): + oor_gauge / oor_live (real floods above the camera's calibrated range: Hancock Jul 29
and Pecatonica Apr 15 with pre-flood bundles, Animas live on Oct 23 with its gauge stored inline), oor_stale
(synthetic gauge dropout during those floods -> lower bound only), muddy_rise / muddy_stale (real turbid rises
within range whose only quality complaints are fog / texture loss).

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
    def __init__(self, cam: str, bundles: Path = BUNDLES):
        self.cam = cam
        self.bundles = bundles
        self.meta = json.loads((bundles / cam / "meta.json").read_text(encoding="utf-8"))
        d = DATA / "derived" / cam
        hf = pd.read_parquet(d / "history" / "frames.parquet")
        hr = pd.read_parquet(d / "history" / "registration.parquet")[["filename", "night", "ok", "n_inliers", "score", "method", "segment"]]
        h = hf.merge(hr, on="filename")
        parts = [h]
        if (d / "frames.parquet").exists():              # the 30-day kill-test window (frozen 20 sites only)
            kf = pd.read_parquet(d / "frames.parquet")
            kr = pd.read_parquet(d / "registration_cascade.parquet")[["filename", "night", "ok", "n_inliers", "score", "method"]]
            parts.append(kf.merge(kr, on="filename").assign(segment="main"))
        self.frames = pd.concat(parts).drop_duplicates("filename").sort_values("time").reset_index(drop=True)
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


def bank_match(site, key, exclude) -> dict:
    """Ground-truth check (v2): what the frame actually registers to, against exactly the bank the episode exposes
    (same deterministic cascade the agent's tool uses). History registration flags alone mislabelled 3 v1 episodes."""
    ctx = tools.ToolContext(mode="eval", bundle_root=BUNDLES, bank_exclude=tuple(exclude),
                            event={"cam_id": site.cam, "reading": {}})
    return tools.call(ctx, "reregister_fullres", {"cam": site.cam, "frame_key": key}).get("best") or {}


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
            keep, n_re = [], 0
            for _, r in fr.iloc[:12].iterrows():
                excl = sorted(set(own + later_refs(site, r["time"])))
                b = bank_match(site, site.key(r["filename"]), excl)
                if b.get("ok") and b.get("ref") == "reference.jpg":
                    continue                                   # registers to the current reference: not a loss
                if b.get("ok") and b.get("calibrated"):
                    if n_re < 2:
                        n_re += 1
                        add("reanchor_banked", "real", site, r["time"], reading(site, r, ["VIEW_CHANGE"]), recent(site, r["time"]),
                            ["SET_REFERENCE"], ["QUARANTINE", "OPEN_TICKET", "DRAFT_ALERT"], args={"SET_REFERENCE": {"ref": b["ref"]}},
                            severity=2, ctx={"bank_exclude": excl},
                            note=f"frame of unlinked {s['segment']} matches earlier calibrated reference {b['ref']} (bank check)")
                    continue
                keep.append(r)
            fr = pd.DataFrame(keep)
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
            fr = fr[[usable(site, site.key(f)) for f in fr["filename"]]] if len(fr) else fr
            fr = fr[[bank_match(site, site.key(f), later_refs(site, t)).get("ref") == ref_file
                     for f, t in zip(fr["filename"], fr["time"])]].iloc[:per_segment] if len(fr) else fr
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
            if not usable(site, site.key(r["filename"])) or \
                    bank_match(site, site.key(r["filename"]), later_refs(site, r["time"])).get("ref") != "reference.jpg":
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


# ---- v3 (D-0009): out-of-range floods and muddy water during rises ---------------------------------

REPLAY = DATA / "derived" / "agent_bundles_replay"
AGENT_EVAL_RAW = DATA / "raw" / "agent_eval"
OOR_FORBID = ["QUARANTINE", "OPEN_TICKET", "MARK_PROVISIONAL", "SET_REFERENCE"]


def tool_ctx(site, now=None, fault=None, inline=None):
    return tools.ToolContext(mode="eval", bundle_root=site.bundles, now=now, gauge_fault=fault, gauge_inline=inline,
                             event={"cam_id": site.cam, "reading": {}})


def history_row(site, when):
    f = site.frames[~site.frames["night"]]
    i = (f["time"] - pd.Timestamp(when, tz="UTC")).abs().idxmin()
    return f.loc[i]


def build_out_of_range():
    """Real floods above the camera's calibrated range, with bundles cut before each flood (so the flood is truly
    out of range for the model), plus Animas on 2026-10-23 (live frames, gauge fetched once and stored inline)."""
    cases = [("NY_East_Branch_Delaware_River_at_Hancock_Staff", "2026-07-26", ["2026-07-29T12:00", "2026-07-29T18:00", "2026-07-30T12:00"]),
             ("WI_East_Branch_Pecatonica_River_near_Blanchardville_Bullet", "2026-04-12", ["2026-04-15T13:00", "2026-04-15T19:00"])]
    for cam, cut, times in cases:
        site = Site(cam, REPLAY / cut)
        for when in times:
            r = history_row(site, when)
            ctx = tool_ctx(site, now=r["time"])
            e = tools.call(ctx, "estimate_stage", {"cam": cam, "frame_key": site.key(r["filename"])})
            q = tools.call(ctx, "image_quality", {"frame_key": site.key(r["filename"])})
            flags = ["OUT_OF_RANGE", "DISAGREE", "RISING"] + (["LOW_QUALITY"] if not q.get("usable") else [])
            g = site.gauge_at(r["time"])[0]
            add("oor_gauge", "real", site, r["time"], reading(site, r, flags, camera_ft=e.get("stage_ft")), recent(site, r["time"]),
                ["DENSIFY", "DRAFT_ALERT"], OOR_FORBID, severity=5, ctx={"bundle_root": site.bundles.relative_to(ROOT).as_posix()},
                note=f"gauge {g:.2f} ft vs calibrated max {site.meta['stage_max']} ft (bundle cut {cut}); camera {e.get('stage_ft')} ft")
    # gauge goes stale during the flood: only a lower bound may be published (flags as W1 would raise them)
    for cam, cut, when, hours in (("NY_East_Branch_Delaware_River_at_Hancock_Staff", "2026-07-26", "2026-07-29T18:00", 4),
                                  ("WI_East_Branch_Pecatonica_River_near_Blanchardville_Bullet", "2026-04-12", "2026-04-15T19:00", 6)):
        site = Site(cam, REPLAY / cut)
        r = history_row(site, when)
        fault = {"kind": "dropout", "hours": hours}
        e = tools.call(tool_ctx(site, now=r["time"]), "estimate_stage", {"cam": cam, "frame_key": site.key(r["filename"])})
        add("oor_stale", "synthetic", site, r["time"], reading(site, r, ["GAUGE_STALE"], camera_ft=e.get("stage_ft"), fault=fault),
            recent(site, r["time"], fault=fault), ["MARK_PROVISIONAL"], ["QUARANTINE", "OPEN_TICKET", "SET_REFERENCE"],
            args={"MARK_PROVISIONAL": {"source": "camera_lower_bound"}}, severity=4, injected={"gauge_fault": fault},
            ctx={"bundle_root": site.bundles.relative_to(ROOT).as_posix(), "gauge_fault": fault},
            note=f"real flood frame, gauge dropout {hours} h injected; last known gauge already above the calibrated max")
    # Animas, live, 2026-10-23: gauge 8.3 ft vs calibrated max 4.57 ft
    cam = "CO_Animas_River_at_Durango"
    site = Site(cam)
    iv = pd.read_parquet(AGENT_EVAL_RAW / f"{cam}_iv_20261023.parquet")
    inline = [[pd.Timestamp(t).isoformat(), float(v)] for t, v in zip(iv["time"], iv["value"])]
    site.gauge = pd.Series(iv["value"].to_numpy(float), index=pd.DatetimeIndex(iv["time"]))
    for jpg in sorted(AGENT_EVAL_RAW.glob(f"{cam}___2026-10-23*.jpg")):
        t = pd.Timestamp(jpg.stem.split("___")[1].replace("-", ":").replace("2026:10:23", "2026-10-23"))
        key = f"data/raw/agent_eval/{jpg.name}"
        row = {"time": t, "filename": jpg.name, "night": False, "ok": True, "n_inliers": 0, "score": 0, "method": "live"}
        e = tools.call(tool_ctx(site, now=t, inline=inline), "estimate_stage", {"cam": cam, "frame_key": key})
        for flags in (["OUT_OF_RANGE", "DISAGREE", "RISING"], ["RISING"]):
            rd = reading(site, row, flags, frame_key=key, camera_ft=e.get("stage_ft"))
            add("oor_live", "real", site, t, rd, [], ["DENSIFY", "DRAFT_ALERT"], OOR_FORBID, severity=5,
                ctx={"gauge_inline": inline}, note=f"live 2026-10-23; flags {'+'.join(flags)} "
                                                   f"({'as W1 will raise them' if len(flags) > 1 else 'as the live cycle raised them'})")


def build_muddy_rises(n_fresh=6, n_stale=3):
    """Real rises within the calibrated range where image_quality's only complaints are fog / texture loss
    (turbid water, covered banks). LOW_QUALITY persisted 2 cycles, so the lens-ticket rule is tempted."""
    cands = []
    for cam in sorted(p.name for p in BUNDLES.iterdir() if (p / "meta.json").exists()):
        site = Site(cam)
        g, f = site.gauge, site.frames
        f = f[~f["night"] & f["ok"] & f["stage_ft"].notna() & (f["stage_ft"] <= site.meta["stage_max"]) & ~f["filename"].isin(EXCLUDE)]
        f = f[f["time"] < pd.Timestamp("2026-10-03", tz="UTC")]
        rise = g.reindex(f["time"], method="ffill").values - g.reindex(f["time"] - pd.Timedelta("1h"), method="ffill").values
        f = f[rise >= 0.1]
        ctx = tool_ctx(site)
        for _, r in f.iterrows():
            iss = set(tools.call(ctx, "image_quality", {"frame_key": site.key(r["filename"])}).get("issues", []))
            if iss and iss <= {"fog", "texture_loss"}:
                cands.append((site, r))
    by_cam: dict[str, list] = {}
    for site, r in cands:
        by_cam.setdefault(site.cam, []).append((site, r))
    order = list(RNG.permutation(sorted(by_cam)))
    picks = [by_cam[c][len(by_cam[c]) // 2] for c in order]
    flag_lq = lambda rr: ["LOW_QUALITY", "RISING"]                                       # noqa: E731
    for site, r in picks[:n_fresh]:
        t = r["time"]
        crest = site.gauge[(site.gauge.index >= t) & (site.gauge.index <= t + pd.Timedelta("6h"))].max()
        alert = bool(crest >= site.meta["stage_p90"])
        add("muddy_rise", "real", site, t, reading(site, r, ["RISING", "LOW_QUALITY"]), recent(site, t, flag_fn=flag_lq),
            ["DENSIFY"] + (["DRAFT_ALERT"] if alert else []), ["QUARANTINE", "OPEN_TICKET", "SET_REFERENCE"],
            severity=5 if alert else 1, note=f"turbid rise; gauge {r['stage_ft']:.2f} ft, 6 h crest {crest:.2f} vs p90 {site.meta['stage_p90']}")
    n = 0
    for site, r in picks[n_fresh:]:
        if n >= n_stale:
            break
        t = r["time"]
        fault = {"kind": "dropout", "hours": 6}
        last = site.gauge_at(t, fault)[0]
        e = tools.call(tool_ctx(site, now=t, fault=fault), "estimate_stage", {"cam": site.cam, "frame_key": site.key(r["filename"])})
        if not e.get("ok") or not e.get("in_calibrated_range") or e.get("near_ceiling") or \
                last is None or last >= site.meta["stage_max"] - site.sigma:
            continue
        add("muddy_stale", "synthetic", site, t, reading(site, r, ["RISING", "LOW_QUALITY", "GAUGE_STALE"], fault=fault),
            recent(site, t, fault=fault, flag_fn=flag_lq), ["MARK_PROVISIONAL"], ["QUARANTINE", "OPEN_TICKET"],
            args={"MARK_PROVISIONAL": {"source": "camera"}}, severity=3, injected={"gauge_fault": fault},
            ctx={"gauge_fault": fault}, note="turbid rise, gauge dropout 6 h injected; camera registers and is in range")
        n += 1


# ---- v4 (D-0013 W2-1): tidal sites ------------------------------------------------------------------

ONBOARD = ROOT / "models" / "onboard"


def tidal_rising_flag(site, t) -> bool:
    """RISING as the live cycle raises it: 3 h gauge rise >= 0.5 ft or stage at/above the site p90."""
    return change(site, t, 3) >= 0.5 or (site.gauge_at(t)[0] or -1e9) >= site.meta["stage_p90"]


def build_tidal():
    """Real tidal episodes: ordinary high tides that the old RISING logic alerted on (must not alert), the live false
    alert Samuel approved on 2026-10-24 (must not alert), and Savannah record-high days (must alert). Labels use the
    site's daily-maximum distribution only (independent of the harmonic model the agent uses)."""
    tid = json.loads((ROOT / "src" / "riversight" / "agent" / "tidal_sites.json").read_text(encoding="utf-8"))
    no_alert = ["DRAFT_ALERT", "OPEN_TICKET", "QUARANTINE", "SET_REFERENCE"]
    for cam, root, n_tide in (("CA_First_Mallard_Branch_nr_Fairfield", BUNDLES, 4), ("GA_Savannah_River_at_USACE_Dock_at_Savannah", ONBOARD, 3)):
        site, dm = Site(cam, root), tid[cam]
        f = site.frames[~site.frames["night"] & site.frames["ok"] & ~site.frames["filename"].isin(EXCLUDE)]
        day_max = site.gauge.resample("1D").max()
        f = f.assign(dmax=day_max.reindex(f["time"].dt.floor("D")).to_numpy())
        tide = f[(f["dmax"] < dm["daily_max_p90"]) & [tidal_rising_flag(site, t) for t in f["time"]]]
        rel = site.bundles.relative_to(ROOT).as_posix()
        for _, r in pick(tide, n_tide, 3).iterrows():
            add("tidal_tide", "real", site, r["time"], reading(site, r, ["RISING"]), recent(site, r["time"]), [], no_alert,
                severity=0, ctx={"bundle_root": rel},
                note=f"ordinary tide: gauge {site.gauge_at(r['time'])[0]:.2f} ft, day max {r['dmax']:.2f} < daily-max p90 {dm['daily_max_p90']}")
        if cam.startswith("GA_"):
            for day in ("2026-05-17", "2026-09-08", "2026-10-10"):
                fd = f[f["time"].dt.strftime("%Y-%m-%d") == day]
                if not len(fd):
                    continue
                levels = [site.gauge_at(t)[0] or -1e9 for t in fd["time"]]
                r = fd.iloc[int(np.argmax(levels))]                   # the frame nearest the day's peak water
                g = site.gauge_at(r["time"])[0]
                if g is None or g < dm["daily_max_p95"]:
                    continue
                add("tidal_flood", "real", site, r["time"], reading(site, r, ["RISING"]), recent(site, r["time"]),
                    ["DENSIFY", "DRAFT_ALERT"], ["QUARANTINE", "SET_REFERENCE"], severity=5, ctx={"bundle_root": rel},
                    note=f"record-high water day (daily max >= p99 {dm['daily_max_p99']}); gauge {g:.2f} ft at the frame")
    # the false alert Samuel approved on the live site (2026-10-24 18:15Z): an incoming tide extrapolated to a 31 ft crest
    cam = "CA_First_Mallard_Branch_nr_Fairfield"
    site = Site(cam)
    iv = pd.read_parquet(AGENT_EVAL_RAW / f"{cam}_iv_20261024.parquet")
    inline = [[pd.Timestamp(t).isoformat(), float(v)] for t, v in zip(iv["time"], iv["value"])]
    site.gauge = pd.Series(iv["value"].to_numpy(float), index=pd.DatetimeIndex(iv["time"]))
    t = pd.Timestamp("2026-10-24T18:15:04Z")
    row = {"time": t, "filename": "live", "night": False, "ok": True, "n_inliers": 0, "score": 0, "method": "live"}
    rd = reading(site, row, ["RISING"], frame_key=f"data/raw/agent_eval/{cam}___2026-10-24T18-15-04Z.jpg", camera_ft=27.725)
    add("tidal_live_false_alert", "real", site, t, rd, [], [], no_alert, severity=0, ctx={"gauge_inline": inline},
        injected={"note": "replays live approval apr-20261024-577f088009 (approved false alert)"},
        note="live 2026-10-24 18:15Z: rules drafted an alert on an incoming tide (+1.17 ft/h, 3 h trend crest 31.3 ft); "
             "Samuel approved it; documented false alert")


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
    build_out_of_range()
    build_muddy_rises()
    build_tidal()
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
