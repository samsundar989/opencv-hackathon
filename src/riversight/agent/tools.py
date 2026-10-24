"""OpenCV tools the agent may call (INTERFACES §4). Pure functions over the site bundle and frames.

Every tool returns a JSON-serialisable dict with a one-line `summary`. Images never go to the LLM — only these
numbers. The OpenCV 5 work behind each tool:

  reregister_fullres    ALIKED + LightGlueMatcher + findHomography(USAC_MAGSAC) against every banked reference
                        (ORB + BFMatcher first as the cheap pass), with the fixed-camera plausibility test
  compare_to_last_good  phaseCorrelate (Hanning window) shift + ZNCC of Sobel structure on non-water blocks
  image_quality         Laplacian variance, dark-channel fog, glare, IR/night, texture loss vs the reference
  estimate_stage        register → warpPerspective → Lab/Sobel block features → ridge scene model → stage ± σ
  render_wet_overlay    flood-height map: tint every block with h* ≤ stage, YuNet face blur, imencode
  get_gauge / get_nws_forecast / fetch_recent_frames   context (USGS IV, NOAA NWPS, NIMS)

`ToolContext.evidence == "flags_only"` is the ablation arm (c): every tool returns only the reading's flags,
so the LLM must decide without OpenCV evidence.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
import pandas as pd

from riversight.agent.store import ROOT, Sink, load_frame

MASK_TOP = 56
SAME_RESP, SAME_SHIFT_PX = 0.06, 25.0        # compare_to_last_good "same view" (calibrated, see there)
IR_MAX_FOG = 0.35                            # a desaturated frame with a lifted dark channel is haze, not night IR
DATA =Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))


# ---- context ----------------------------------------------------------------------------------------

@dataclass
class ToolContext:
    mode: str = "live"                         # live | replay | eval
    evidence: str = "full"                     # full | flags_only (ablation arm c)
    bundle_root: Path = field(default_factory=lambda: Path(os.environ.get("RIVERSIGHT_BUNDLES", ROOT / "models" / "sites")))
    sink: Sink | None = None
    now: pd.Timestamp | None = None            # replay/eval clock: gauge and frame lists are cut here
    gauge_fault: dict | None = None            # eval only: {"kind": dropout|offset|drift|flatline, ...}
    bank_exclude: tuple[str, ...] = ()         # eval only: reference files hidden from the bank
    gauge_inline: list | None = None           # eval only: [[iso time, ft], ...] when the history cache lacks it
    event: dict | None = None
    write_overlays: bool = True

    @property
    def reading(self) -> dict:
        return (self.event or {}).get("reading") or {}


_bundles: dict[tuple[str, str], Any] = {}


def bundle(ctx: ToolContext, cam: str):
    from riversight.live.bundle import SiteModel
    key = (str(ctx.bundle_root), cam)
    if key not in _bundles:
        d = Path(ctx.bundle_root) / cam
        if not (d / "meta.json").exists():
            raise KeyError(f"no model bundle for camera {cam!r} under {ctx.bundle_root}")
        _bundles[key] = SiteModel(d)
    return _bundles[key]


def _r(x, nd=3):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def _cam(ctx: ToolContext, cam: str | None) -> str:
    return cam or (ctx.event or {}).get("cam_id")


def _frame(key: str) -> np.ndarray:
    img = load_frame(key)
    if img is None:
        raise FileNotFoundError(f"frame not found: {key}")
    return img


# ---- registration helpers ---------------------------------------------------------------------------

# ONE detector/matcher instance per method per process; only each reference's keypoints + descriptors are cached
# (~1k × 128 floats). The first version built an ALIKED+LightGlue instance per reference image (~1.3 GB each):
# the eval jobs committed 31-40 GiB each and took the host down on Oct 23 (worker-q 3741-3743).
_registrars: dict[str, Any] = {}
_ref_feats: dict[tuple[str, str], tuple] = {}
_reg_lock = threading.RLock()        # the shared ALIKED/LightGlue objects are used by one thread at a time
MAX_REF_FEATS = 512


def _registrar(ref_path: str, method: str, ref_img: np.ndarray):
    """The shared registrar for `method`, pointed at `ref_path`'s cached reference features. Call under _reg_lock."""
    from riversight.killtest import Cfg, make_registrar
    if method not in _registrars:
        _registrars[method] = make_registrar(Cfg(), method)
    R = _registrars[method]
    k = (ref_path, method)
    if k not in _ref_feats:
        if len(_ref_feats) >= MAX_REF_FEATS:
            _ref_feats.clear()
        R.set_reference(ref_img)
        _ref_feats[k] = (R._ref_kp, R._ref_desc, R._ref_shape)
    R._ref_kp, R._ref_desc, R._ref_shape = _ref_feats[k]
    return R


def _register(img: np.ndarray, ref_path: str, ref_img: np.ndarray, methods=("orb", "aliked")) -> dict:
    """Cascade registration (killtest) + fixed-camera plausibility. Returns a compact dict incl. H."""
    from riversight.killtest import Cfg, homography_plausible
    cfg = Cfg()
    best = {"ok": False, "inliers": 0, "score": 0.0, "method": None, "H": None, "corner_px": None}
    if img.shape[:2] != ref_img.shape[:2]:
        img = cv2.resize(img, (ref_img.shape[1], ref_img.shape[0]), interpolation=cv2.INTER_AREA)
    for m in methods:
        with _reg_lock:
            r = _registrar(ref_path, m, ref_img).register(img)
        plaus, disp = (homography_plausible(r.H, ref_img.shape[:2], cfg.max_corner_frac, cfg.area_range)
                       if r.H is not None else (False, None))
        cand = {"ok": bool(r.ok and plaus), "inliers": int(r.n_inliers), "score": round(float(r.score), 3),
                "method": r.method, "H": r.H, "corner_px": _r(disp, 1), "reproj_px": _r(r.reproj_err_px, 2)}
        if cand["ok"] or cand["inliers"] > best["inliers"]:
            best = cand
        if cand["ok"]:
            break
    return best


def reference_bank(ctx: ToolContext, cam: str) -> list[dict]:
    S = bundle(ctx, cam)
    bank = [{"file": "reference.jpg", "linked": True, "H_to_main": None, "segment": "main", "start": S.meta.get("calib_start")}]
    for e in S.meta.get("extra_references", []):
        bank.append({k: e.get(k) for k in ("file", "linked", "H_to_main", "segment", "start")})
    return [b for b in bank if b["file"] not in ctx.bank_exclude]


def _ref_img(ctx: ToolContext, cam: str, file: str) -> np.ndarray:
    return _frame(str(Path(ctx.bundle_root) / cam / file))


# ---- tools ------------------------------------------------------------------------------------------

def reregister_fullres(ctx: ToolContext, cam: str, frame_key: str) -> dict:
    cam = _cam(ctx, cam)
    img = _frame(frame_key)
    rows = []
    for b in reference_bank(ctx, cam):
        p = str(Path(ctx.bundle_root) / cam / b["file"])
        r = _register(img, p, _ref_img(ctx, cam, b["file"]))
        rows.append({"ref": b["file"], "segment": b["segment"], "calibrated": bool(b["linked"]),
                     **{k: v for k, v in r.items() if k != "H"}})
    rows.sort(key=lambda x: (x["ok"], x["inliers"]), reverse=True)
    best = rows[0] if rows else None
    if best and best["ok"]:
        where = "the current reference" if best["ref"] == "reference.jpg" else \
            f"banked reference {best['ref']} ({'calibrated, maps to main geometry' if best['calibrated'] else 'UNcalibrated view'})"
        s = f"registers to {where}: {best['inliers']} inliers, corner shift {best['corner_px']} px ({best['method']})"
    else:
        s = f"no plausible registration to any of {len(rows)} banked references (best {best['inliers'] if best else 0} inliers)"
    return {"resolution": list(img.shape[:2]), "n_refs": len(rows), "best": best, "all": rows[:6], "summary": s}


def _small_gray(img: np.ndarray) -> np.ndarray:
    g = cv2.cvtColor(img[MASK_TOP:], cv2.COLOR_BGR2GRAY)
    return cv2.resize(g, (320, 172), interpolation=cv2.INTER_AREA).astype(np.float32)


def _zncc(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a - a.mean(), b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else 0.0


def compare_to_last_good(ctx: ToolContext, cam: str, frame_key: str) -> dict:
    cam = _cam(ctx, cam)
    last_key, last_t = None, None
    for r in reversed((ctx.event or {}).get("recent") or []):
        if (r.get("registration") or {}).get("ok") and r.get("frame_key") and r.get("frame_key") != frame_key:
            last_key, last_t = r["frame_key"], r.get("t_frame")
            break
    ref = load_frame(last_key) if last_key else None
    if ref is None:
        last_key, last_t, ref = "reference.jpg", "reference", _ref_img(ctx, cam, "reference.jpg")
    img = _frame(frame_key)
    if img.shape[:2] != ref.shape[:2]:
        img = cv2.resize(img, (ref.shape[1], ref.shape[0]), interpolation=cv2.INTER_AREA)
    a, b = _small_gray(img), _small_gray(ref)
    win = cv2.createHanningWindow(a.shape[::-1], cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(b, a, win)
    scale = ref.shape[1] / 320.0
    ga = cv2.magnitude(cv2.Sobel(a, cv2.CV_32F, 1, 0), cv2.Sobel(a, cv2.CV_32F, 0, 1))
    gb = cv2.magnitude(cv2.Sobel(b, cv2.CV_32F, 1, 0), cv2.Sobel(b, cv2.CV_32F, 0, 1))
    # static structure = blocks the flood-height map says do NOT respond to water (banks, piers, buildings)
    static = None
    try:
        S = bundle(ctx, cam)
        from riversight.vision.scene_features import GRID
        acc = S.fhm.acc.reshape(GRID)
        m = cv2.resize((acc < 0.65).astype(np.uint8), (320, 180), interpolation=cv2.INTER_NEAREST)[180 - 172:]
        static = m.astype(bool) if m.mean() > 0.1 else None
    except KeyError:
        pass
    sim_all = _zncc(ga, gb)
    sim_static = _zncc(ga[static], gb[static]) if static is not None else sim_all
    shift_px = float(np.hypot(dx, dy) * scale)
    # thresholds from scripts/agent_calibrate_tools.py (results/agent_eval/tool_calibration.csv): on 120 clean
    # and 42 real new-view history frames this calls 83 % of clean frames "same view" and 88 % of new views not
    verdict = "same view" if resp >= SAME_RESP and shift_px <= SAME_SHIFT_PX else \
        ("shifted view" if resp >= SAME_RESP else "different or obscured view")
    return {"against": last_key, "against_t": last_t, "shift_px": _r(shift_px, 1), "dx_px": _r(dx * scale, 1),
            "dy_px": _r(dy * scale, 1), "phase_response": _r(resp), "structure_similarity": _r(sim_all),
            "static_structure_similarity": _r(sim_static), "verdict": verdict,
            "summary": f"{verdict}: shift {shift_px:.1f} px (response {resp:.2f}), static-structure similarity "
                       f"{sim_static:.2f} vs {'last good frame' if last_key != 'reference.jpg' else 'reference'}"}


def image_quality(ctx: ToolContext, frame_key: str, cam: str | None = None) -> dict:
    from riversight.live.quality import image_quality as iq
    cam = _cam(ctx, cam)
    img = _frame(frame_key)
    q = iq(img)
    lv = {}
    texture_loss = None
    try:
        S = bundle(ctx, cam)
        lv = S.meta.get("quality") or {}
        ref = S.reference()
        if ref is not None:
            a = _small_gray(img if img.shape[:2] == ref.shape[:2] else cv2.resize(img, ref.shape[1::-1], interpolation=cv2.INTER_AREA))
            b = _small_gray(ref)
            ea = cv2.blur(cv2.magnitude(cv2.Sobel(a, cv2.CV_32F, 1, 0), cv2.Sobel(a, cv2.CV_32F, 0, 1)), (16, 16))
            eb = cv2.blur(cv2.magnitude(cv2.Sobel(b, cv2.CV_32F, 1, 0), cv2.Sobel(b, cv2.CV_32F, 0, 1)), (16, 16))
            tex = eb > np.percentile(eb, 40)
            texture_loss = float(((ea < 0.3 * eb) & tex).sum() / max(tex.sum(), 1))
    except KeyError:
        pass
    blurred = bool(lv and q["lap_var"] < 0.6 * lv.get("lap_var_p5", 0))
    foggy = bool(lv and q["fog_score"] > max(lv.get("fog_p95", 1.0) * 1.15, lv.get("fog_p95", 1.0) + 0.05))
    glare = bool(q["glare_frac"] > max(0.08, 2 * lv.get("glare_p95", 0.0)))
    occluded = bool(texture_loss is not None and texture_loss > 0.30)
    night = bool(q["night_img"] and q["fog_score"] < IR_MAX_FOG)
    foggy = foggy or bool(q["night_img"] and not night)          # bright + desaturated = haze
    issues = [n for n, f in (("ir_or_night", night), ("blurred", blurred), ("fog", foggy),
                             ("glare", glare), ("texture_loss", occluded)) if f]
    usable = not issues
    return {**q, "texture_loss_frac": _r(texture_loss), "site_lap_var_p5": _r(lv.get("lap_var_p5")),
            "site_fog_p95": _r(lv.get("fog_p95")), "issues": issues, "usable": usable,
            "summary": ("usable daylight frame" if usable else "NOT usable: " + ", ".join(issues)) +
                       f" (lap_var {q['lap_var']:.0f} vs site p5 {lv.get('lap_var_p5', float('nan')):.0f}, "
                       f"fog {q['fog_score']:.2f}, texture loss {texture_loss if texture_loss is not None else float('nan'):.2f})"}


def _registered_features(ctx: ToolContext, cam: str, img: np.ndarray, ref: str | None) -> tuple[np.ndarray | None, dict]:
    from riversight.live.bundle import frame_features
    S = bundle(ctx, cam)
    bank = {b["file"]: b for b in reference_bank(ctx, cam)}
    tried = [ref] if ref else ["reference.jpg"]
    if not ref:
        tried += [f for f, b in bank.items() if f != "reference.jpg" and b["linked"] and b["H_to_main"]]
    shape = tuple(S.meta.get("ref_shape") or S.reference().shape[:2])
    last = {"ok": False, "inliers": 0}
    for f in tried:
        if f not in bank and f != "reference.jpg":
            continue
        r = _register(img, str(Path(ctx.bundle_root) / cam / f), _ref_img(ctx, cam, f))
        last = {**{k: v for k, v in r.items() if k != "H"}, "ref": f}
        if not r["ok"]:
            continue
        H = np.asarray(r["H"], float).reshape(3, 3)
        if f != "reference.jpg":
            if not bank[f].get("H_to_main"):
                continue                      # uncalibrated view: no mapping into the scene model
            H = np.asarray(bank[f]["H_to_main"], float).reshape(3, 3) @ H
        im = img if img.shape[:2] == shape else cv2.resize(img, (shape[1], shape[0]), interpolation=cv2.INTER_AREA)
        return frame_features(im, H, shape), last
    return None, last


def estimate_stage(ctx: ToolContext, cam: str, frame_key: str, ref: str | None = None) -> dict:
    cam = _cam(ctx, cam)
    S = bundle(ctx, cam)
    img = _frame(frame_key)
    F, reg = _registered_features(ctx, cam, img, ref)
    sigma = float(S.meta.get("sigma_ft") or float("nan"))
    if F is None:
        return {"ok": False, "registration": reg, "stage_ft": None, "sigma_ft": _r(sigma),
                "summary": f"no estimate: frame does not register to a calibrated reference (best {reg.get('inliers', 0)} inliers)"}
    raw = float(S.predict_raw(F)[0])
    from riversight.calib.flood_height_map import FloodHeightMap  # noqa: F401  (documented dependency)
    wet = S.fhm.wet(F[None], S.fhm.reliable(float(S.a["min_acc"])))[0]
    lo, hi = S.meta.get("stage_min", S.meta.get("stage_p05")), S.meta.get("stage_max", S.meta.get("stage_p95"))
    in_range = lo is None or (lo - 0.5 <= raw <= hi + 0.5)
    # D-0009: a raw estimate within σ of the calibrated ceiling may be saturated — the true stage can be far
    # higher (Hancock Jul 29: camera ~10.1 ft at a 17-18 ft gauge, ceiling 11.18 ft). Report it as a lower bound.
    near_ceiling = bool(hi is not None and np.isfinite(sigma) and raw >= hi - sigma)
    out = {"ok": True, "stage_ft": _r(raw), "sigma_ft": _r(sigma), "registration": reg,
           "wet_reliable_blocks": int(wet.sum()), "reliable_blocks": int(len(wet)),
           "calibrated_range_ft": [_r(lo), _r(hi)], "in_calibrated_range": bool(in_range),
           "near_ceiling": near_ceiling, "stage_max_ft": _r(hi),
           "stage_p90_ft": _r(S.meta.get("stage_p90")), "summary": ""}
    out["summary"] = (f"camera stage {raw:.2f} ± {sigma:.2f} ft (registered to {reg['ref']}, {reg['inliers']} inliers)"
                      + ("" if in_range else f"; OUTSIDE calibrated range {lo:.2f}–{hi:.2f} ft (extrapolation)")
                      + (f"; NEAR the calibrated ceiling {hi:.2f} ft: may be saturated, true stage could be higher"
                         if near_ceiling else ""))
    return out


MIN_WET_BLOCKS = 6


def clean_wet_mask(wet: np.ndarray) -> np.ndarray:
    """Display-only cleanup of the block wet mask: morphological close then open (3×3 blocks) and drop connected
    components smaller than MIN_WET_BLOCKS — isolated tree/shadow blocks the flood-height map marks reliable
    would otherwise speckle the overlay. Decisions never use this mask."""
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    m = cv2.morphologyEx(cv2.morphologyEx(wet, cv2.MORPH_CLOSE, k), cv2.MORPH_OPEN, k)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= MIN_WET_BLOCKS
    return keep[lab].astype(np.uint8)


def render_wet_overlay(ctx: ToolContext, cam: str, frame_key: str, stage_ft: float, label: str = "") -> dict:
    from riversight.vision.privacy import blur_faces
    from riversight.vision.scene_features import GRID
    cam = _cam(ctx, cam)
    S = bundle(ctx, cam)
    ref = S.reference()
    img = load_frame(frame_key)
    base = ref.copy()
    if img is not None:
        r = _register(img, str(Path(ctx.bundle_root) / cam / "reference.jpg"), ref)
        if r["ok"]:
            from riversight.vision.register import warp_to_reference
            im = img if img.shape[:2] == ref.shape[:2] else cv2.resize(img, ref.shape[1::-1], interpolation=cv2.INTER_AREA)
            base = warp_to_reference(im, np.asarray(r["H"], float).reshape(3, 3), ref.shape[:2])
    # D-0011: draw only blocks hydraulically connected to the river (W1's live.bundle connected inundation,
    # the same function the dashboard slider uses); bundles without it fall back to the speckle cleanup
    if hasattr(S, "wet_connected"):
        wet = S.wet_connected(float(stage_ft)).astype(np.uint8)
    else:
        wet = clean_wet_mask(S.wet_mask(float(stage_ft)).astype(np.uint8))
    m = cv2.resize(wet, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)
    tint = base.copy()
    tint[m] = (0.45 * tint[m] + 0.55 * np.array([255, 120, 20])).astype(np.uint8)
    edges = cv2.Canny(m.astype(np.uint8) * 255, 50, 150)
    tint[edges > 0] = (255, 255, 255)
    txt = f"blue = newly under water at {float(stage_ft):.2f} ft ({label or 'stage'})  |  RiverSight  |  USGS HIVIS (public domain)"
    cv2.rectangle(tint, (0, tint.shape[0] - 28), (tint.shape[1], tint.shape[0]), (0, 0, 0), -1)
    cv2.putText(tint, txt, (8, tint.shape[0] - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    tint, n_faces = blur_faces(tint)
    key = None
    if ctx.write_overlays and ctx.sink is not None:
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        key = ctx.sink.put_jpeg(f"live/overlays/{cam}/agent_{ts}_{float(stage_ft):.2f}ft.jpg", tint)
    frac = float(wet.mean())
    return {"overlay_key": key, "stage_ft": _r(stage_ft), "wet_block_frac": _r(frac), "n_wet_blocks": int(wet.sum()),
            "faces_blurred": n_faces, "summary": f"overlay at {float(stage_ft):.2f} ft: {100 * frac:.1f}% of the view under water"
                                                  + (f" -> {key}" if key else "")}


# ---- context tools ----------------------------------------------------------------------------------

def _nwis_to_cam(ctx: ToolContext, nwis_id: str) -> str | None:
    root = Path(ctx.bundle_root)
    for d in root.iterdir() if root.exists() else []:
        p = d / "meta.json"
        if p.exists() and str(json.loads(p.read_text(encoding="utf-8")).get("nwis_id")) == str(nwis_id).lstrip("USGS-"):
            return d.name
    return None


def _history_gauge(cam: str) -> pd.Series:
    parts = []
    for p in (DATA / "derived" / cam / "history" / "stage.parquet", DATA / "derived" / cam / "stage.parquet"):
        if p.exists():
            s = pd.read_parquet(p)
            parts.append(pd.Series(s["value"].to_numpy(float), index=pd.DatetimeIndex(s["time"])))
    if not parts:
        return pd.Series(dtype=float)
    g = pd.concat(parts).sort_index()
    return g[~g.index.duplicated(keep="last")]


def apply_gauge_fault(g: pd.Series, now: pd.Timestamp, fault: dict | None) -> pd.Series:
    if not fault or not len(g):
        return g
    k = fault["kind"]
    since = now - pd.Timedelta(hours=float(fault.get("hours", 0)))
    g = g.copy()
    if k == "dropout":
        g = g[g.index < since]
    elif k == "offset":
        g[g.index >= since] += float(fault["ft"])
    elif k == "drift":
        dt = (g.index[g.index >= since] - since).total_seconds() / 86400.0
        g[g.index >= since] += float(fault["ft_per_day"]) * dt
    elif k == "flatline":
        before = g[g.index < since]
        if len(before):
            g[g.index >= since] = before.iloc[-1]
    return g


def gauge_series(ctx: ToolContext, cam: str, hours: float) -> pd.Series:
    """Recent gauge readings (ft) up to the context clock, with the eval fault applied."""
    if ctx.mode == "live":
        from riversight.data.nwis import legacy_iv_multi
        S = bundle(ctx, cam)
        now = pd.Timestamp.now(tz="UTC")
        got = legacy_iv_multi([S.meta["nwis_id"]], (now - pd.Timedelta(hours=hours)).to_pydatetime(), now.to_pydatetime())
        df = next(iter(got.values()), None)
        if df is None or not len(df):
            return pd.Series(dtype=float)
        return pd.Series(df["value"].to_numpy(float), index=pd.DatetimeIndex(df["time"])).sort_index()
    now = ctx.now
    if ctx.gauge_inline:
        g = pd.Series([float(v) for _, v in ctx.gauge_inline], index=pd.DatetimeIndex([pd.Timestamp(t) for t, _ in ctx.gauge_inline]))
    else:
        g = _history_gauge(cam)
    g = g[(g.index <= now) & (g.index > now - pd.Timedelta(hours=hours))]
    return apply_gauge_fault(g, now, ctx.gauge_fault)


def get_gauge(ctx: ToolContext, nwis_id: str | None = None, hours: float = 24) -> dict:
    cam = (_nwis_to_cam(ctx, nwis_id) if nwis_id else None) or _cam(ctx, None)
    hours = float(min(max(hours or 24, 1), 168))
    g = gauge_series(ctx, cam, hours)
    now = ctx.now if ctx.mode != "live" else pd.Timestamp.now(tz="UTC")
    if not len(g):
        return {"n": 0, "latest_ft": None, "age_min": None, "summary": f"no gauge readings in the last {hours:.0f} h (gauge offline)"}
    age = (now - g.index[-1]).total_seconds() / 60
    d = np.diff(g.values)

    def chg(h):
        prev = g[g.index <= g.index[-1] - pd.Timedelta(hours=h)]
        return _r(g.iloc[-1] - prev.iloc[-1]) if len(prev) else None
    flat = 0.0
    for i in range(len(g) - 1, 0, -1):
        if abs(g.iloc[i] - g.iloc[i - 1]) > 1e-6:
            break
        flat = (g.index[-1] - g.index[i - 1]).total_seconds() / 3600
    big = int(np.argmax(np.abs(d))) if len(d) else 0
    # a sensor jump stands alone; a real rise has neighbouring increments of the same sign
    others = np.abs(np.delete(d[max(big - 12, 0): big + 13], min(big, 12))) if len(d) > 2 else np.array([0.0])
    isolation = float(abs(d[big]) / (np.percentile(others, 90) + 0.01)) if len(d) else 0.0
    hourly = g.resample("1h").last().dropna().iloc[-12:]
    out = {"n": int(len(g)), "latest_ft": _r(g.iloc[-1]), "latest_time": g.index[-1].isoformat(), "age_min": _r(age, 0),
           "change_1h_ft": chg(1), "change_6h_ft": chg(6), "change_24h_ft": chg(24), "min_ft": _r(g.min()), "max_ft": _r(g.max()),
           "max_step_ft": _r(d[big]) if len(d) else None, "max_step_time": g.index[big + 1].isoformat() if len(d) else None,
           "step_isolation": _r(isolation, 1), "flat_hours": _r(flat, 1), "hourly_last12": [_r(v, 2) for v in hourly.values]}
    try:
        smax = bundle(ctx, cam).meta.get("stage_max")
    except KeyError:
        smax = None
    out["camera_calibrated_max_ft"] = _r(smax)
    out["above_camera_range"] = bool(smax is not None and g.iloc[-1] > smax)
    out["summary"] = (f"gauge {out['latest_ft']} ft, {age:.0f} min old; 1h {out['change_1h_ft']}, 6h {out['change_6h_ft']} ft; "
                      f"largest single step {out['max_step_ft']} ft (isolation x{isolation:.1f} vs neighbouring steps); "
                      f"flat for {flat:.1f} h"
                      + (f"; ABOVE the camera's calibrated range (max {smax:.2f} ft)" if out["above_camera_range"] else ""))
    return out


def get_nws_forecast(ctx: ToolContext, nwis_id: str | None = None) -> dict:
    if ctx.mode != "live":
        return {"available": False, "summary": "no archived NWPS forecast for this replay time (forecast not used)"}
    import httpx
    cam = (_nwis_to_cam(ctx, nwis_id) if nwis_id else None) or _cam(ctx, None)
    sid = str(bundle(ctx, cam).meta["nwis_id"])
    try:
        with httpx.Client(timeout=15, headers={"User-Agent": "RiverSight/0.1 (OpenCV AI Competition 2026)"}) as c:
            g = c.get(f"https://api.water.noaa.gov/nwps/v1/gauges/{sid}")
            if g.status_code != 200:
                return {"available": False, "summary": f"no NWPS forecast point for USGS {sid}"}
            gj = g.json()
            lid = gj.get("lid") or sid
            f = c.get(f"https://api.water.noaa.gov/nwps/v1/gauges/{lid}/stageflow/forecast").json()
        data = f.get("data") or []
        cats = (gj.get("flood") or {}).get("categories") or {}
        if not data:
            return {"available": False, "lid": lid, "flood_categories_ft": {k: v.get("stage") for k, v in cats.items()},
                    "summary": f"NWPS gauge {lid} has no forecast series"}
        crest = max(data, key=lambda r: r.get("primary", -1e9))
        return {"available": True, "lid": lid, "crest_ft": _r(crest.get("primary")), "crest_time": crest.get("validTime"),
                "flood_categories_ft": {k: v.get("stage") for k, v in cats.items()},
                "summary": f"NWS forecast crest {crest.get('primary')} ft at {crest.get('validTime')} (gauge {lid})"}
    except Exception as e:                                                        # noqa: BLE001
        return {"available": False, "summary": f"NWPS unavailable ({type(e).__name__})"}


def fetch_recent_frames(ctx: ToolContext, cam: str | None = None, n: int = 4) -> dict:
    from riversight.live.quality import image_quality as iq
    cam = _cam(ctx, cam)
    n = int(min(max(n or 4, 1), 8))
    rows = []
    if ctx.mode == "live":
        for r in ((ctx.event or {}).get("recent") or [])[-n:]:
            rows.append({"frame_key": r.get("frame_key"), "t": r.get("t_frame")})
    else:
        fr = []
        for p in (DATA / "derived" / cam / "history" / "frames.parquet", DATA / "derived" / cam / "frames.parquet"):
            if p.exists():
                fr.append(pd.read_parquet(p, columns=["filename", "time"]))
        f = pd.concat(fr).drop_duplicates("filename").sort_values("time")
        f = f[f["time"] < ctx.now].iloc[-n:]
        rows = [{"frame_key": f"data/raw/720/{cam}/{fn}", "t": t.isoformat()} for fn, t in zip(f["filename"], f["time"])]
    for r in rows:
        img = load_frame(r["frame_key"]) if r.get("frame_key") else None
        if img is None:
            r["usable"] = None
            continue
        q = iq(img)
        r.update(lap_var=q["lap_var"], fog_score=q["fog_score"], night=q["night_img"])
    s = ", ".join(f"{(r['t'] or '')[11:16]} {'night' if r.get('night') else ('lap ' + str(int(r['lap_var'])) if r.get('lap_var') is not None else 'n/a')}"
                  for r in rows)
    return {"frames": rows, "summary": f"{len(rows)} previous frames: {s}"}


# ---- registry ---------------------------------------------------------------------------------------

TOOLS: dict[str, Callable[..., dict]] = {
    "reregister_fullres": reregister_fullres, "compare_to_last_good": compare_to_last_good,
    "image_quality": image_quality, "estimate_stage": estimate_stage, "render_wet_overlay": render_wet_overlay,
    "get_gauge": get_gauge, "get_nws_forecast": get_nws_forecast, "fetch_recent_frames": fetch_recent_frames,
}

_S = {"type": "string"}
_N = {"type": "number"}
TOOL_SPECS = [
    {"name": "reregister_fullres", "description": "Register the frame (ALIKED+LightGlue+MAGSAC, ORB first) against every banked reference view of this camera. Tells you whether the frame matches the current reference, a banked calibrated reference (re-anchor candidate), an uncalibrated known view, or nothing.",
     "props": {"cam": _S, "frame_key": _S}, "req": ["cam", "frame_key"]},
    {"name": "compare_to_last_good", "description": "phaseCorrelate shift and Sobel-structure similarity (on non-water blocks) between this frame and the last well-registered frame. Distinguishes a small bump, a different view, and an obscured lens.",
     "props": {"cam": _S, "frame_key": _S}, "req": ["cam", "frame_key"]},
    {"name": "image_quality", "description": "Laplacian sharpness, dark-channel fog, glare, IR/night and texture loss vs the reference, compared with this site's own calibration levels. Says whether the frame is usable.",
     "props": {"frame_key": _S}, "req": ["frame_key"]},
    {"name": "estimate_stage", "description": "Camera-only river stage (ft) ± sigma from the calibrated scene model. Registers the frame first; fails if it cannot register to a calibrated reference. Optional ref = a banked reference file to register against.",
     "props": {"cam": _S, "frame_key": _S, "ref": _S}, "req": ["cam", "frame_key"]},
    {"name": "render_wet_overlay", "description": "Render what would be under water at stage_ft onto this camera's view (flood-height map). Use for the current stage and for a forecast crest; returns the overlay image key for an alert.",
     "props": {"cam": _S, "frame_key": _S, "stage_ft": _N, "label": _S}, "req": ["cam", "frame_key", "stage_ft"]},
    {"name": "get_gauge", "description": "Recent USGS gauge readings for this site: latest value and age, 1/6/24 h change, largest single-interval step, how long it has been flat.",
     "props": {"nwis_id": _S, "hours": _N}, "req": []},
    {"name": "get_nws_forecast", "description": "NOAA NWPS river forecast crest and flood categories for this gauge, if one exists.",
     "props": {"nwis_id": _S}, "req": []},
    {"name": "fetch_recent_frames", "description": "The n most recent previous frames of this camera with sharpness/fog/night, to tell a transient problem from a persistent one.",
     "props": {"cam": _S, "n": _N}, "req": []},
]


def bedrock_tool_config(extra: list[dict] | None = None) -> dict:
    tools = [{"toolSpec": {"name": t["name"], "description": t["description"],
                           "inputSchema": {"json": {"type": "object", "properties": t["props"], "required": t["req"]}}}}
             for t in TOOL_SPECS]
    return {"tools": tools + (extra or [])}


_tl = threading.local()        # a caching wrapper (scripts/agent_eval.py) reports original compute ms here


def timed_call(ctx: ToolContext, name: str, args: dict) -> tuple[dict, int]:
    """(result, ms) — ms is the original compute time when a cache served the result."""
    _tl.ms = None
    t0 = time.perf_counter()
    res = call(ctx, name, args)
    ms = _tl.ms if getattr(_tl, "ms", None) is not None else round(1000 * (time.perf_counter() - t0))
    _tl.ms = None
    return res, ms


def call(ctx: ToolContext, name: str, args: dict) -> dict:
    """Run one tool by name. Errors come back as a result (never raise into the agent loop)."""
    if name not in TOOLS:
        return {"error": f"unknown tool {name}", "summary": f"unknown tool {name}"}
    if ctx.evidence == "flags_only":
        fl = ctx.reading.get("flags") or []
        return {"flags": fl, "summary": f"(evidence withheld) reading flags: {', '.join(fl) or 'none'}"}
    try:
        return TOOLS[name](ctx, **{k: v for k, v in (args or {}).items() if v is not None})
    except TypeError as e:
        return {"error": f"bad arguments: {e}", "summary": f"bad arguments for {name}"}
    except Exception as e:                                                        # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}", "summary": f"{name} failed: {type(e).__name__}"}
