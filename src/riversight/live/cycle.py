"""The live cycle (SPRINT W1 step 2): newest NIMS frame per site → one Reading (INTERFACES §2).

Per site, per cycle:
  1. newest frame (public `usgs-nims-images` bucket, 720-px variant)
  2. daylight: solar elevation ≥ −3° and the SLICE_01 pixel night test
  3. registration cascade ORB → ALIKED + LightGlue (OpenCV 5) → USAC_MAGSAC, plausibility-checked; then the
     view-change bank (linked segment references, H = H_link · H_seg)
  4. image quality (Laplacian variance, dark-channel fog, glare)
  5. scene model → raw stage → per-site Kalman (state persisted in the store)
  6. gauge (legacy NWIS IV, one batched request for every site)
  7. flags
  8. wet overlay: blocks with h* ≤ estimated stage, warped back into the frame with WARP_INVERSE_MAP
  9. YuNet face blur on everything that leaves the pipeline
 10. latest.json, the day's jsonl, the overlay and frame JPGs, and live/index.json

Flagged readings (any flag except NIGHT alone) go to `riversight.agent.handle` (W2); if that raises,
to `riversight.agent.rules.handle`. Approvals land in live/approvals/<id>.json.

  python -m riversight.live.cycle --local               writes to live_local/
  python -m riversight.live.cycle --s3 <bucket>         writes to the bucket (the Graviton worker)
  python -m riversight.live.cycle --replay <cam> <t0> <t1>   replays cached history into live_local/replay/<cam>/

KleidiCV on arm64 (#29794, #29816): resizes use INTER_AREA and warps use BORDER_CONSTANT only.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
import pandas as pd

from riversight.live.bundle import KalmanState, SiteModel, frame_features
from riversight.live.quality import image_quality
from riversight.live.store import LocalStore, S3Store

ROOT = Path(__file__).resolve().parents[3]
BUNDLES = Path(os.environ.get("RIVERSIGHT_BUNDLES", ROOT / "models" / "sites"))
MASK_TOP = 56
NIGHT_SUN_ELEV = -3.0
MAX_CORNER_FRAC, AREA_RANGE = 0.12, (0.8, 1.25)

# flag thresholds (SPRINT_W1 step 2)
VIEW_MIN_INLIER_RATIO = 0.25
VIEW_MAX_REPROJ_PX = 4.0
GAUGE_STALE_MIN = 90
DISAGREE_SIGMAS, DISAGREE_RUN = 2.5, 3
RISE_FT, RISE_HOURS = 0.5, 3.0
CADENCE_MIN, DENSE_CADENCE_MIN = 30, 15
FRAME_MAX_AGE_MIN = 24 * 60     # look back a day for the newest frame (status "stale" past FRAME_STALE_MIN)
FRAME_STALE_MIN = 120
RELEASE_RUN, RELEASE_SIGMAS = 3, 2.0
RECENT_N = 24


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(t: datetime | pd.Timestamp | None) -> str | None:
    if t is None:
        return None
    return pd.Timestamp(t).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def _r(x, d=3):
    return None if x is None or not np.isfinite(x) else round(float(x), d)


# ---- environment facts ------------------------------------------------------------------------------

def code_sha() -> str:
    if os.environ.get("RIVERSIGHT_CODE_SHA"):
        return os.environ["RIVERSIGHT_CODE_SHA"]
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=5).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def opencv_info() -> dict:
    info = cv2.getBuildInformation()
    return {"version": cv2.__version__, "file": cv2.__file__,
            "cool": "cool" in cv2.__file__.lower() or "COOL" in info,
            "kleidicv": "KleidiCV" in info or "kleidicv" in info.lower()}


# ---- gauge ------------------------------------------------------------------------------------------

class Gauge:
    """Recent stage per NWIS site: {nwis_id: Series(time → ft)}. Live = one batched legacy IV request."""

    def __init__(self, series: dict[str, pd.Series]):
        self.series = series

    @classmethod
    def fetch(cls, nwis_ids: list[str], now: datetime, hours: float = 8) -> "Gauge":
        from riversight.data.nwis import legacy_iv_multi
        try:
            got = legacy_iv_multi(sorted(set(nwis_ids)), now - timedelta(hours=hours), now, timeout=60)
        except Exception as e:                     # gauge outage is a product feature, not a crash
            print(f"gauge fetch failed: {e!r}", flush=True)
            got = {}
        return cls({k: pd.Series(v["value"].to_numpy(float), index=pd.DatetimeIndex(v["time"])) for k, v in got.items()})

    @classmethod
    def from_parquet(cls, nwis_id: str, paths: list[Path]) -> "Gauge":
        parts = []
        for p in paths:
            if p.exists():
                s = pd.read_parquet(p)
                parts.append(pd.Series(s["value"].to_numpy(float), index=pd.DatetimeIndex(s["time"])))
        g = pd.concat(parts).sort_index() if parts else pd.Series(dtype=float)
        return cls({nwis_id: g[~g.index.duplicated(keep="last")]})

    def at(self, nwis_id: str, t: datetime) -> tuple[float | None, pd.Timestamp | None, float | None]:
        """(latest value at or before t, its time, rise over the last RISE_HOURS in ft)."""
        s = self.series.get(nwis_id)
        if s is None or not len(s):
            return None, None, None
        s = s[s.index <= pd.Timestamp(t)]
        if not len(s):
            return None, None, None
        t_last = s.index[-1]
        past = s[s.index <= t_last - pd.Timedelta(hours=RISE_HOURS)]
        rise = float(s.iloc[-1] - past.iloc[-1]) if len(past) else None
        return float(s.iloc[-1]), t_last, rise


# ---- frames -----------------------------------------------------------------------------------------

@dataclass
class Frame:
    filename: str
    time: datetime
    img: np.ndarray


def newest_frame(nims, cam: str, now: datetime, cache: Path) -> Frame | None:
    from riversight.data.nims import parse_filename
    files = nims.list_files(cam, after=now - timedelta(minutes=FRAME_MAX_AGE_MIN), before=now, limit=5, recent=True)
    if not files:
        return None
    fn = max(files, key=lambda f: parse_filename(f)[1])
    p = nims.download(cam, fn, cache, prefix="720")
    img = cv2.imread(str(p))
    return None if img is None else Frame(fn, parse_filename(fn)[1], img)


# ---- registration -----------------------------------------------------------------------------------

class SiteRegistrar:
    """ORB (cheap) → ALIKED+LightGlue (OpenCV 5) cascade against the main reference, then the bank."""

    _aliked_cache: dict = {}

    def __init__(self, model: SiteModel):
        from riversight.vision.register import Registrar
        self.model = model
        self.ref = model.reference()
        self.orb = Registrar(use_aliked=False, mask_rows_top=MASK_TOP)
        self.orb.set_reference(self.ref)
        self.bank = []
        for e in model.meta.get("extra_references", []):
            if e.get("linked") and e.get("H_to_main"):
                img = cv2.imread(str(model.dir / e["file"]))
                if img is not None and img.shape[:2] == self.ref.shape[:2]:
                    self.bank.append((e["file"], img, np.array(e["H_to_main"], float).reshape(3, 3)))

    _shared = None                      # ONE ALIKED + LightGlue instance per process (~1.3 GB in the DNN engine)
    _ref_feats: dict = {}               # (cam, ref name) → cached reference keypoints / descriptors

    def _aliked_register(self, ref_name: str, ref: np.ndarray, img: np.ndarray):
        from riversight.killtest import ALIKED_ONNX, LIGHTGLUE_ONNX
        from riversight.vision.register import Registrar
        cls = SiteRegistrar
        if cls._shared is None:
            cls._shared = Registrar(ALIKED_ONNX, LIGHTGLUE_ONNX, use_aliked=True, mask_rows_top=MASK_TOP)
        R, key = cls._shared, (self.model.cam_id, ref_name)
        if key not in cls._ref_feats:
            R.set_reference(ref)
            cls._ref_feats[key] = (R._ref_kp, R._ref_desc, R._ref_shape)
        R._ref_kp, R._ref_desc, R._ref_shape = cls._ref_feats[key]
        return R.register(img)

    @staticmethod
    def plausible(H: np.ndarray, shape) -> bool:
        h, w = shape
        c = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
        m = cv2.perspectiveTransform(c, H).reshape(-1, 2)
        disp = float(np.max(np.linalg.norm(m - c.reshape(-1, 2), axis=1)))
        area = cv2.contourArea(m.astype(np.float32)) / float(w * h)
        return disp <= MAX_CORNER_FRAC * w and AREA_RANGE[0] <= area <= AREA_RANGE[1]

    def _summ(self, r, ref_name: str, H=None) -> dict:
        ok = bool(r.ok and r.H is not None and self.plausible(r.H, self.ref.shape[:2]))
        return {"ok": ok, "inliers": int(r.n_inliers), "matches": int(r.n_matches),
                "inlier_ratio": _r(r.n_inliers / max(r.n_matches, 1), 3), "reproj_px": _r(r.reproj_err_px, 2),
                "score": _r(r.score, 3), "ref": ref_name, "method": r.method.replace("+", "_"),
                "H": (H if H is not None else r.H) if ok else None}

    def register(self, img: np.ndarray) -> dict:
        if img.shape[:2] != self.ref.shape[:2]:
            img = cv2.resize(img, (self.ref.shape[1], self.ref.shape[0]), interpolation=cv2.INTER_AREA)
        best = self._summ(self.orb.register(img), "reference.jpg")
        if best["ok"]:
            return best
        s = self._summ(self._aliked_register("reference.jpg", self.ref, img), "reference.jpg")
        if s["ok"]:
            return s
        best = s if (s["inliers"] or 0) >= (best["inliers"] or 0) else best
        for name, ref_img, H_link in self.bank:            # known alternate views (camera moved and came back)
            r = self._aliked_register(name, ref_img, img)
            if r.ok and r.H is not None:
                H = H_link @ r.H
                s = self._summ(r, name, H)
                if s["ok"] and self.plausible(H, self.ref.shape[:2]):
                    return s
        return best


# ---- overlay ----------------------------------------------------------------------------------------

def render_overlay(img: np.ndarray, model: SiteModel, H: np.ndarray | None, stage: float | None,
                   caption: list[str]) -> np.ndarray:
    """Frame with the blocks under water at `stage` tinted blue (h* map warped back into frame geometry)."""
    out = img.copy()
    if H is not None and stage is not None and np.isfinite(stage):
        rh, rw = model.meta["ref_shape"]
        wet = clean_mask(model.wet_mask(stage))
        wet_ref = cv2.resize(wet, (rw, rh), interpolation=cv2.INTER_NEAREST)
        wet_img = cv2.warpPerspective(wet_ref, np.asarray(H, float), (img.shape[1], img.shape[0]),
                                      flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_CONSTANT)
        m = wet_img > 0
        tint = np.zeros_like(out)
        tint[:] = (255, 140, 30)
        out[m] = cv2.addWeighted(out, 0.55, tint, 0.45, 0)[m]
        cnts, _ = cv2.findContours(wet_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(out, cnts, -1, (255, 200, 80), 1, cv2.LINE_AA)
    band = 10 + 22 * len(caption)
    y0 = img.shape[0] - band
    out[y0:] = cv2.addWeighted(out[y0:], 0.35, np.zeros_like(out[y0:]), 0.65, 0)
    for k, line in enumerate(caption):
        cv2.putText(out, line, (10, y0 + 22 * (k + 1) - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1,
                    cv2.LINE_AA)
    return out


def clean_mask(wet_blocks: np.ndarray, min_blocks: int = 3) -> np.ndarray:
    """Block-grid wet mask → uint8 0/255 without isolated specks (components smaller than `min_blocks`)."""
    m = wet_blocks.astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_blocks
    return (keep[lab] * 255).astype(np.uint8)


def blur(img: np.ndarray) -> np.ndarray:
    from riversight.vision.privacy import blur_faces
    return blur_faces(img)[0]


def jpg(img: np.ndarray, q: int = 85) -> bytes:
    ok, b = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    if not ok:
        raise RuntimeError("imencode failed")
    return b.tobytes()


# ---- per-site step ----------------------------------------------------------------------------------

def sun_elev(lat: float, lon: float, t: datetime) -> float:
    from riversight.killtest import sun_elevation_deg
    return float(sun_elevation_deg(lat, lon, pd.Series([pd.Timestamp(t)]))[0])


def flood_state(stage: float | None, meta: dict) -> str:
    if stage is None or not np.isfinite(stage):
        return "unknown"
    if stage >= meta["flood_ft"]:
        return "flood"
    if stage >= meta["flood_elevated_ft"]:
        return "elevated"
    return "normal"


def site_status(reading: dict, state: dict) -> str:
    """Dashboard pill: ok | provisional (gauge down, camera-only) | above_range | quarantined | night |
    view_change | stale (newest frame older than 2 h)."""
    if state.get("quarantined"):
        return "quarantined"
    if "OUT_OF_RANGE" in reading["flags"]:
        return "above_range" if "GAUGE_STALE" not in reading["flags"] else "above_range_provisional"
    if (reading.get("frame_age_min") or 0) > FRAME_STALE_MIN:
        return "stale"
    if "NIGHT" in reading["flags"]:
        return "night"
    if "VIEW_CHANGE" in reading["flags"]:
        return "view_change"
    if "GAUGE_STALE" in reading["flags"] or state.get("provisional"):
        return "provisional"
    return "ok"


def release_quarantine(state: dict, model: SiteModel, frame: Frame, raw: float | None, g_fresh: float | None,
                       sigma: float, store, t_cycle: datetime) -> bool:
    """D-0009 W1-6: lift a quarantine after RELEASE_RUN consecutive cycles with registration OK and
    |raw camera − gauge| ≤ 2σ. The Kalman filter restarts from the current raw estimate. Logged."""
    good = raw is not None and g_fresh is not None and sigma and abs(raw - g_fresh) <= RELEASE_SIGMAS * sigma
    state["release_run"] = state.get("release_run", 0) + 1 if good else 0
    if state["release_run"] < RELEASE_RUN:
        return False
    q = state.pop("quarantined")
    state["release_run"] = 0
    ks, _, _ = model.kalman_step(KalmanState(), frame.time.timestamp(), raw)
    state["kalman"] = ks.to_json()
    store.append_jsonl(f"live/agent/{t_cycle:%Y-%m-%d}.jsonl", {
        "event_id": f"{model.cam_id}:{iso(frame.time)}:release", "cam_id": model.cam_id, "t_frame": iso(frame.time),
        "decided_by": "rules", "flags": [], "actions": [{"type": "QUARANTINE_RELEASED", "args": {"since": q.get("since")},
                                                         "needs_approval": False}],
        "rationale": f"{RELEASE_RUN} consecutive registered frames within {RELEASE_SIGMAS:g} sigma of the gauge."})
    return True


def run_site(model: SiteModel, frame: Frame, store, gauge: Gauge, t_cycle: datetime, reg_cache: dict,
             agent_fn: Callable[[dict], dict] | None = None, mode: str = "live") -> dict:
    cam, meta = model.cam_id, model.meta
    state = store.get_json(f"live/state/{cam}.json") or {}
    ts = frame.time.strftime("%Y%m%dT%H%M%SZ")
    q = image_quality(frame.img, MASK_TOP)
    elev = sun_elev(meta["lat"], meta["lon"], frame.time)
    night = elev < NIGHT_SUN_ELEV or q["night_img"]
    flags: list[str] = []
    reg = {"ok": False, "inliers": 0, "inlier_ratio": None, "reproj_px": None, "ref": None, "method": None}
    raw = cam_x = None
    H = None
    if night:
        flags.append("NIGHT")
    else:
        if cam not in reg_cache:
            reg_cache[cam] = SiteRegistrar(model)
        reg = reg_cache[cam].register(frame.img)
        H = reg.pop("H")
        reg["H_frame_to_ref"] = None if H is None else [round(float(v), 6) for v in np.asarray(H).ravel()]
        if (not reg["ok"] or (reg["inlier_ratio"] or 0) < VIEW_MIN_INLIER_RATIO
                or (reg["reproj_px"] or 0) > VIEW_MAX_REPROJ_PX):
            flags.append("VIEW_CHANGE")
        ql = meta.get("quality", {})
        if q["lap_var"] < ql.get("lap_var_p5", -1) or q["fog_score"] > ql.get("fog_p95", 9):
            flags.append("LOW_QUALITY")
        if reg["ok"]:
            img = frame.img
            if img.shape[:2] != tuple(meta["ref_shape"]):
                img = cv2.resize(img, (meta["ref_shape"][1], meta["ref_shape"][0]), interpolation=cv2.INTER_AREA)
            raw = float(model.predict_raw(frame_features(img, H, tuple(meta["ref_shape"])))[0])
            if not state.get("quarantined"):
                ks, cam_x, _ = model.kalman_step(KalmanState.from_json(state.get("kalman")), frame.time.timestamp(), raw)
                state["kalman"] = ks.to_json()
    g_val, g_t, g_rise = gauge.at(meta["nwis_id"], t_cycle)
    g_age = None if g_t is None else (pd.Timestamp(t_cycle) - g_t).total_seconds() / 60
    if g_age is None or g_age > GAUGE_STALE_MIN:
        flags.append("GAUGE_STALE")
    g_fresh = g_val if "GAUGE_STALE" not in flags else None
    sigma = meta.get("sigma_ft") or 0.0
    released = release_quarantine(state, model, frame, raw, g_fresh, sigma, store, t_cycle) if state.get("quarantined") else False
    if released:
        cam_x = raw
    # D-0009 W1-1: the camera cannot read above (or the gauge is outside) the calibrated range
    s_lo, s_hi = meta["stage_min"], meta["stage_max"]
    cam_high = (raw is not None and raw >= s_hi - sigma) or (cam_x is not None and cam_x >= s_hi - sigma)
    gauge_out = g_fresh is not None and (g_fresh > s_hi or g_fresh < s_lo - sigma)
    at_least = None
    if cam_high or gauge_out:
        flags.append("OUT_OF_RANGE")
        if cam_high or (g_fresh is not None and g_fresh > s_hi):
            at_least = s_hi
    if gauge_out:
        flags.append("DISAGREE")                    # immediately: the camera cannot vouch for this stage
    elif cam_x is not None and g_fresh is not None and sigma and not cam_high:
        state["disagree_run"] = state.get("disagree_run", 0) + 1 if abs(cam_x - g_fresh) > DISAGREE_SIGMAS * sigma else 0
        if state["disagree_run"] >= DISAGREE_RUN:
            flags.append("DISAGREE")
    recent = state.get("recent", [])
    cam_rise = None
    if cam_x is not None:
        old = [r for r in recent if r.get("camera_stage_ft") is not None and
               (frame.time - pd.Timestamp(r["t_frame"]).to_pydatetime()).total_seconds() >= RISE_HOURS * 3600 * 0.9]
        if old:
            cam_rise = cam_x - old[-1]["camera_stage_ft"]
    cam_num = None if at_least is not None else cam_x          # never a camera number above the calibrated range
    stage_for_state = g_fresh if g_fresh is not None else (at_least if at_least is not None else cam_x)
    fs = flood_state(stage_for_state, meta)
    if (g_rise is not None and g_rise >= RISE_FT) or (cam_rise is not None and cam_rise >= RISE_FT) \
            or fs in ("elevated", "flood"):
        flags.append("RISING")
    stage_draw = cam_num if cam_num is not None else (at_least if at_least is not None and cam_x is not None else g_fresh)
    cam_txt = (f">= {at_least:.2f} ft (above calibrated range)" if at_least is not None and cam_x is not None
               else f"{cam_num:.2f} ft +/- {sigma:.2f}" if cam_num is not None else "n/a")
    caption = [f"{cam[:48]}  {frame.time:%Y-%m-%d %H:%M}Z",
               "camera " + cam_txt + "   gauge " + (f"{g_val:.2f} ft" if g_val is not None else "n/a"),
               "blue = under water at this stage (RiverSight live model)" if stage_draw is not None and H is not None
               else "no overlay (" + ("night" if night else "not registered") + ")"]
    overlay = render_overlay(frame.img, model, H, stage_draw, caption)
    frame_key, overlay_key = f"live/frames/{cam}/{ts}.jpg", f"live/overlays/{cam}/{ts}.jpg"
    store.put_bytes(frame_key, jpg(blur(frame.img)), "image/jpeg", "max-age=31536000")
    store.put_bytes(overlay_key, jpg(blur(overlay)), "image/jpeg", "max-age=31536000")
    frame_age = (pd.Timestamp(t_cycle) - pd.Timestamp(frame.time)).total_seconds() / 60
    reading = {
        "cam_id": cam, "t_frame": iso(frame.time), "t_cycle": iso(t_cycle), "daylight": not night,
        "frame_age_min": _r(frame_age, 0),
        "sun_elev_deg": _r(elev, 1), "frame_key": frame_key, "overlay_key": overlay_key, "frame_name": frame.filename,
        "registration": reg, "quality": {k: v for k, v in q.items() if k != "night_img"},
        "camera_raw_ft": _r(raw), "camera_stage_ft": _r(cam_num),
        "camera_sigma_ft": _r(sigma) if cam_num is not None else None,
        "camera_at_least_ft": _r(at_least) if at_least is not None and cam_x is not None else None,
        "calibrated_range_ft": [_r(s_lo), _r(s_hi)],
        "gauge_stage_ft": _r(g_val), "gauge_time": iso(g_t), "gauge_age_min": _r(g_age, 0),
        "gauge_rise_3h_ft": _r(g_rise), "camera_rise_3h_ft": _r(cam_rise), "flood_state": fs, "flags": flags,
        "model_sha": meta["model_sha"][:12], "code_sha": code_sha(), "opencv": opencv_info(), "mode": mode,
    }
    if not night and reg["ok"]:                     # D-0009 W1-2: remembered for night / stale display
        state["last_daylight"] = {k: reading[k] for k in (
            "t_frame", "frame_key", "overlay_key", "camera_stage_ft", "camera_sigma_ft", "camera_at_least_ft",
            "gauge_stage_ft")} | {"H_frame_to_ref": reg.get("H_frame_to_ref")}
    reading["last_daylight"] = state.get("last_daylight")
    decision = None
    if agent_fn is not None and [f for f in flags if f != "NIGHT"]:
        decision = call_agent(agent_fn, reading, recent, meta, mode)
        apply_decision(decision, reading, state, store, t_cycle)
        reading["agent"] = {"event_id": decision.get("event_id"), "decided_by": decision.get("decided_by"),
                            "actions": [a.get("type") for a in decision.get("actions", [])],
                            "rationale": decision.get("rationale"), "approval_id": decision.get("approval_id"),
                            "tokens_in": decision.get("tokens_in"), "tokens_out": decision.get("tokens_out")}
    reading["status"] = site_status(reading, state)
    reading["provisional"] = "GAUGE_STALE" in flags and (cam_num is not None or reading["camera_at_least_ft"] is not None)
    slim = {k: reading[k] for k in ("t_frame", "camera_stage_ft", "gauge_stage_ft", "flags")}
    state["recent"] = (recent + [slim])[-RECENT_N:]
    state["last_frame"], state["last_t"] = frame.filename, iso(frame.time)
    store.put_json(f"live/sites/{cam}/latest.json", reading)
    store.append_jsonl(f"live/sites/{cam}/{frame.time:%Y-%m-%d}.jsonl", reading)
    store.put_json(f"live/state/{cam}.json", state)
    return reading


# ---- agent hook -------------------------------------------------------------------------------------

def load_agent() -> tuple[Callable[[dict], dict] | None, Callable[[dict], dict]]:
    from riversight.agent import rules
    try:
        from riversight import agent
        return agent.handle, rules.handle
    except Exception:
        traceback.print_exc()
        return None, rules.handle


_AGENT = None


AGENT_TIMEOUT_S = 300


def default_agent_fn(event: dict) -> dict:
    """W2's agent in a short-lived spawned process, so whatever its OpenCV tools load (each ALIKED+LightGlue
    instance is ~1.5 GB on arm64) is returned to the OS when the call ends. Falls back to the rules in-process
    on timeout or crash. RIVERSIGHT_AGENT_ISOLATE=0 runs it in-process (tests, replay)."""
    if os.environ.get("RIVERSIGHT_AGENT_ISOLATE", "1") == "0":
        return _agent_in_process(event)
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor
    try:
        with ProcessPoolExecutor(1, mp_context=mp.get_context("spawn")) as ex:
            return ex.submit(_agent_in_process, event).result(timeout=AGENT_TIMEOUT_S)
    except Exception:
        traceback.print_exc()
        from riversight.agent import rules
        d = rules.handle(event)
        d.setdefault("decided_by", "rules")
        return d


def _agent_in_process(event: dict) -> dict:
    """W2's agent, falling back to the deterministic rules if import or the call fails (INTERFACES §3)."""
    global _AGENT
    if _AGENT is None:
        _AGENT = load_agent()
    primary, fallback = _AGENT
    if primary is not None:
        try:
            return primary(event)
        except Exception:
            traceback.print_exc()
    d = fallback(event)
    d.setdefault("decided_by", "rules")
    return d


def call_agent(agent_fn, reading: dict, recent: list, meta: dict, mode: str) -> dict:
    event = {"event_id": f"{reading['cam_id']}:{reading['t_frame']}", "cam_id": reading["cam_id"],
             "reading": reading, "recent": recent, "site_meta": meta, "mode": mode}
    t0 = time.perf_counter()
    try:
        d = agent_fn(event)
    except Exception:
        traceback.print_exc()
        from riversight.agent import rules
        d = rules.handle(event)
    d = dict(d or {})
    d.setdefault("event_id", event["event_id"])
    d["cam_id"] = reading["cam_id"]
    d["t_frame"] = reading["t_frame"]
    d["flags"] = reading["flags"]
    d["ms"] = round((time.perf_counter() - t0) * 1000)
    return d


def apply_decision(d: dict, reading: dict, state: dict, store, t_cycle: datetime):
    """Autonomous actions change site state (reversible, logged); approval actions become pending items."""
    pending = []
    for a in d.get("actions", []):
        typ = a.get("type")
        if a.get("needs_approval") or typ in ("DRAFT_ALERT", "OPEN_TICKET"):
            pending.append(a)
        elif typ == "QUARANTINE":
            state["quarantined"] = {"since": iso(t_cycle), "why": d.get("rationale")}
        elif typ == "MARK_PROVISIONAL":
            state["provisional"] = {"since": iso(t_cycle)}
        elif typ == "DENSIFY":
            hours = float((a.get("args") or {}).get("hours", 6))
            state["densify_until"] = iso(t_cycle + timedelta(hours=hours))
        elif typ == "SET_REFERENCE":
            state["reference_override"] = a.get("args")
            if state.pop("quarantined", None):
                state["release_run"] = 0
                state["quarantine_released"] = {"at": iso(t_cycle), "by": "SET_REFERENCE"}
    if "GAUGE_STALE" not in reading["flags"]:
        state.pop("provisional", None)
    if pending:
        aid = d.get("approval_id") or uuid.uuid4().hex[:12]
        d["approval_id"] = aid
        store.put_json(f"live/approvals/{aid}.json", {
            "approval_id": aid, "status": "pending", "created": iso(t_cycle), "cam_id": reading["cam_id"],
            "event_id": d.get("event_id"), "actions": pending, "rationale": d.get("rationale"),
            "overlay_key": reading["overlay_key"], "reading": {k: reading[k] for k in (
                "t_frame", "camera_stage_ft", "camera_sigma_ft", "gauge_stage_ft", "flood_state", "flags")}})
        notify_approval(aid, reading, pending, d.get("rationale"))
    store.append_jsonl(f"live/agent/{t_cycle:%Y-%m-%d}.jsonl", d)


def notify_approval(aid: str, reading: dict, actions: list, rationale: str | None):
    topic = os.environ.get("RIVERSIGHT_SNS_TOPIC")
    site = os.environ.get("RIVERSIGHT_SITE_URL", "")
    if not topic:
        return
    try:
        import boto3
        boto3.client("sns").publish(
            TopicArn=topic, Subject=f"RiverSight approval needed: {reading['cam_id'][:60]}"[:99],
            Message=(f"{', '.join(a.get('type', '?') for a in actions)} for {reading['cam_id']} at {reading['t_frame']}\n"
                     f"Camera {reading['camera_stage_ft']} ft, gauge {reading['gauge_stage_ft']} ft, flags {reading['flags']}\n"
                     f"Why: {rationale}\n\nReview: {site}/approvals.html#{aid}\n"))
    except Exception:
        traceback.print_exc()


# ---- cycle ------------------------------------------------------------------------------------------

def load_models(bundles: Path = BUNDLES, only: list[str] | None = None) -> list[SiteModel]:
    return [SiteModel(d) for d in sorted(Path(bundles).iterdir())
            if (d / "meta.json").exists() and not d.name.startswith(".") and (not only or d.name in only)]


def due(state: dict | None, now: datetime) -> bool:
    if not state or not state.get("last_t"):
        return True
    dense = state.get("densify_until") and pd.Timestamp(state["densify_until"]) > pd.Timestamp(now)
    gap = (pd.Timestamp(now) - pd.Timestamp(state["last_t"])).total_seconds() / 60
    return gap >= (DENSE_CADENCE_MIN if dense else CADENCE_MIN) - 2


def run_cycle(store, models: list[SiteModel], agent_fn=default_agent_fn, now: datetime | None = None,
              cache: Path | None = None, force: bool = False) -> dict:
    from riversight.data.nims import NimsClient
    t0 = time.perf_counter()
    now = now or utcnow()
    cache = cache or Path(os.environ.get("RIVERSIGHT_FRAME_CACHE", ROOT / "live_local" / "cache"))
    gauge = Gauge.fetch([m.meta["nwis_id"] for m in models], now)
    nims = NimsClient(api_key=os.environ.get("USGS_API_KEY"))
    reg_cache: dict = {}
    sites, errors = [], []
    prev = {s["cam_id"]: s for s in ((store.get_json("live/index.json") or {}).get("sites", []))}
    for m in models:
        cam = m.cam_id
        try:
            state = store.get_json(f"live/state/{cam}.json")
            if not force and not due(state, now):
                sites.append(prev.get(cam) or {"cam_id": cam, "status": "pending"})
                continue
            fr = newest_frame(nims, cam, now, cache)
            if fr is None or (state and state.get("last_frame") == fr.filename):
                old = prev.get(cam) or {"cam_id": cam}
                sites.append({**old, "cam_id": cam, "status": old.get("status", "no_frame"),
                              "note": "no frame in the last 24 h" if fr is None else "frame unchanged"})
                continue
            r = run_site(m, fr, store, gauge, now, reg_cache, agent_fn)
            sites.append(slim_reading(r, m.meta))
            print(f"{cam}: cam {r['camera_stage_ft']} gauge {r['gauge_stage_ft']} flags {r['flags']}", flush=True)
        except Exception as e:
            traceback.print_exc()
            errors.append({"cam_id": cam, "error": repr(e)[:300]})
            sites.append({**(prev.get(cam) or {}), "cam_id": cam, "status": "error", "error": repr(e)[:200]})
    nims.close()
    idx = {"cycle_started": iso(now), "cycle_ms": round((time.perf_counter() - t0) * 1000),
           "n_sites": len(models), "n_ok": sum(1 for s in sites if s.get("status") == "ok"),
           "n_flagged": sum(1 for s in sites if [f for f in s.get("flags", []) if f != "NIGHT"]),
           "n_errors": len(errors), "errors": errors, "code_sha": code_sha(), "opencv": opencv_info(), "sites": sites}
    store.put_json("live/index.json", idx)
    store.append_jsonl(f"live/cycles/{now:%Y-%m-%d}.jsonl", {k: v for k, v in idx.items() if k != "sites"})
    from riversight.live.proof import proof, put_metrics
    try:
        store.put_json("live/proof.json", proof(models))
    except Exception:
        traceback.print_exc()
    put_metrics(idx, [s["agent"] for s in sites if s.get("agent") and s.get("t_cycle") == iso(now)])
    return idx


def slim_reading(r: dict, meta: dict) -> dict:
    keep = ("cam_id", "t_frame", "t_cycle", "daylight", "overlay_key", "camera_stage_ft", "camera_sigma_ft",
            "camera_at_least_ft", "calibrated_range_ft", "gauge_stage_ft", "gauge_age_min", "flood_state", "flags",
            "status", "provisional", "agent", "frame_age_min")
    out = {k: r.get(k) for k in keep}
    out.update(lat=meta["lat"], lon=meta["lon"], tier=meta["tier"], nwis_id=meta["nwis_id"],
               reg_ok=r["registration"]["ok"],
               last_daylight_overlay_key=(r.get("last_daylight") or {}).get("overlay_key"),
               last_daylight_t=(r.get("last_daylight") or {}).get("t_frame"))
    return out


# ---- replay -----------------------------------------------------------------------------------------

def replay(cam: str, t0: str, t1: str, out: Path, agent_fn=default_agent_fn, bundles: Path = BUNDLES,
           data: Path | None = None, step_min: int = CADENCE_MIN) -> list[dict]:
    """Replay cached history frames of one camera through the live per-site step (W2's eval uses this)."""
    from riversight.data.nims import parse_filename
    data = data or Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))
    m = SiteModel(Path(bundles) / cam)
    store = LocalStore(out)
    lo, hi = pd.Timestamp(t0, tz="UTC") if pd.Timestamp(t0).tzinfo is None else pd.Timestamp(t0), \
        pd.Timestamp(t1, tz="UTC") if pd.Timestamp(t1).tzinfo is None else pd.Timestamp(t1)
    files = sorted((data / "raw" / "720" / cam).glob(f"{cam}___*.jpg"))
    files = [(parse_filename(p.name)[1], p) for p in files]
    files = [(t, p) for t, p in files if lo <= pd.Timestamp(t) < hi]
    gauge = Gauge.from_parquet(m.meta["nwis_id"], [data / "derived" / cam / "history" / "stage.parquet",
                                                   data / "derived" / cam / "stage.parquet"])
    reg_cache: dict = {}
    out_rows, last = [], None
    for t, p in files:
        if last is not None and (t - last).total_seconds() < (step_min - 2) * 60:
            continue
        img = cv2.imread(str(p))
        if img is None:
            continue
        r = run_site(m, Frame(p.name, t, img), store, gauge, t, reg_cache, agent_fn, mode="replay")
        out_rows.append(r)
        last = t
    return out_rows


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m riversight.live.cycle")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--local", nargs="?", const=str(ROOT / "live_local"), metavar="DIR")
    g.add_argument("--s3", metavar="BUCKET")
    g.add_argument("--replay", nargs=3, metavar=("CAM", "T0", "T1"))
    ap.add_argument("--bundles", type=Path, default=BUNDLES)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--no-agent", action="store_true")
    ap.add_argument("--force", action="store_true", help="process every site regardless of cadence")
    ap.add_argument("--out", type=Path, help="replay output dir (default live_local/replay/<cam>)")
    a = ap.parse_args(argv)
    agent_fn = None if a.no_agent else default_agent_fn
    if a.replay:
        cam, t0, t1 = a.replay
        rows = replay(cam, t0, t1, a.out or ROOT / "live_local" / "replay" / cam, agent_fn, a.bundles)
        print(f"replayed {len(rows)} frames; flagged {sum(1 for r in rows if r['flags'])}")
        return
    store = LocalStore(Path(a.local)) if a.local else S3Store(a.s3)
    idx = run_cycle(store, load_models(a.bundles, a.only), agent_fn, force=a.force)
    print(json.dumps({k: v for k, v in idx.items() if k != "sites"}, default=str))
    sys.exit(0 if idx["n_errors"] < idx["n_sites"] else 1)


if __name__ == "__main__":
    main()
