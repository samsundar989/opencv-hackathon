"""SLICE_01 kill test: registration → automatic transects → classical waterline → projective stage.

Per site (all choices made on the 20-day fit window; the 10 test days are only scored):
  pass 1  night flag, ORB+USAC_MAGSAC registration of every daytime frame to one reference
          (chained through the last good frame when the direct match fails)
  map     per-pixel correlation between brightness-normalized appearance and gauge stage over the
          fit window → bands that flip land↔water as stage moves → transects across those bands
  pass 2  warp each registered frame, sample transect profiles, detect the boundary (two detectors)
  fit     per transect: projective u(h) fitted on fit days 1–14, scored on fit days 15–20 (blocked
          CV) → transect + detector selection; refit on all 20 fit days → invert on the test days,
          fuse transects by weighted median. Baselines: isotonic lookup, persistence-24h.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import pandas as pd

from riversight.geometry.projective import ProjectiveModel, fit_isotonic_lookup, fit_robust
from riversight.vision.register import Registrar, warp_to_reference
from riversight.vision.transect import Transect, detect_changepoint, detect_transition, profile_features

DETECTORS = ("changepoint", "transition")


@dataclass
class Cfg:
    mask_top: int = 56             # USGS overlay text band on 720-px frames (rows)
    night_sat: float = 12.0        # mean HSV saturation below this → IR/night frame
    night_val: float = 45.0        # mean brightness below this → night
    chain_hours: float = 3.0       # max age of the 'last good frame' used for chained registration
    map_scale: float = 0.5         # correlation map resolution relative to the frame
    corr_floor: float = 0.35       # minimum |corr| for a pixel to belong to a stage-sensitive band
    max_components: int = 3
    transects_per_component: int = 3
    half_width: int = 3
    prior_sigma: float = 40.0
    prior_hours: float = 6.0
    min_conf: float = 0.05
    cv_days: float = 6.0           # last N fit days used as the CV block for selection
    max_cv_mae_ft: float = 1.0     # transects worse than this on CV are dropped
    inlier_px: float = 6.0
    reg_method: str = "cascade"    # ORB → ALIKED+LightGlue (OpenCV 5) fallback; "orb"/"aliked" for ablations
    min_gap_min: float = 30.0      # thin 15-min cameras to a 30-min cadence


@dataclass
class SiteResult:
    cam_id: str
    metrics: dict = field(default_factory=dict)
    transects: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def _progress(frac: float):
    p = os.environ.get("WORKERQ_PROGRESS")
    if p:
        try:
            Path(p).write_text(f"{frac:.4f}")
        except OSError:
            pass


def is_night(img: np.ndarray, cfg: Cfg) -> bool:
    small = cv2.resize(img[cfg.mask_top:], None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    return bool(hsv[..., 1].mean() < cfg.night_sat or hsv[..., 2].mean() < cfg.night_val)


def sharpness(img: np.ndarray, cfg: Cfg) -> float:
    g = cv2.cvtColor(img[cfg.mask_top:], cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def choose_reference(frames: pd.DataFrame, cfg: Cfg, n_cand: int = 60) -> tuple[int, np.ndarray]:
    """Sharpest daytime fit-window frame whose stage is near the fit-window median."""
    f = frames[frames["window"] == "fit"].dropna(subset=["stage_ft"])
    med = f["stage_ft"].median()
    spread = max(f["stage_ft"].quantile(0.95) - f["stage_ft"].quantile(0.05), 0.05)
    near = f[(f["stage_ft"] - med).abs() <= 0.15 * spread]
    if len(near) < 10:
        near = f.iloc[(f["stage_ft"] - med).abs().argsort()[:max(10, len(f) // 5)]]
    cand = near.iloc[np.linspace(0, len(near) - 1, min(n_cand, len(near))).astype(int)]
    best, best_i, best_img = -1.0, -1, None
    for i, r in cand.iterrows():
        img = cv2.imread(r["path"])
        if img is None or is_night(img, cfg):
            continue
        sh = sharpness(img, cfg)
        if sh > best:
            best, best_i, best_img = sh, i, img
    if best_img is None:
        raise RuntimeError("no daytime reference candidate")
    return best_i, best_img


MODELS = Path(os.environ.get("RIVERSIGHT_MODELS", Path(__file__).resolve().parents[2] / "models" / "onnx"))
ALIKED_ONNX = MODELS / "aliked-n16rot-top1k-640.onnx"
LIGHTGLUE_ONNX = MODELS / "aliked_lightglue.onnx"


def make_registrar(cfg: Cfg, method: str) -> Registrar:
    if method == "aliked":
        return Registrar(ALIKED_ONNX, LIGHTGLUE_ONNX, use_aliked=True, mask_rows_top=cfg.mask_top)
    return Registrar(use_aliked=False, mask_rows_top=cfg.mask_top)


def register_frames(frames: pd.DataFrame, ref: np.ndarray, cfg: Cfg, method: str = "cascade",
                    progress=(0.0, 0.7)) -> pd.DataFrame:
    """Pass 1 (the expensive one): night flag + registration of every daytime frame to the reference.

    method="cascade": ORB+MAGSAC first (cheap); frames it cannot register go to ALIKED+LightGlue+MAGSAC
    (OpenCV 5), and finally to a chained match through the last good frame. "orb"/"aliked" force one.
    """
    stages = {"cascade": ["orb", "aliked"], "orb": ["orb"], "aliked": ["aliked"]}[method]
    regs = {m: make_registrar(cfg, m) for m in stages}
    for R in regs.values():
        R.set_reference(ref)
    chain = make_registrar(cfg, stages[-1])
    rows = []
    last_good = None  # (time, H_to_ref, image-or-None once loaded into `chain`)
    n = len(frames)
    for j, (i, r) in enumerate(frames.iterrows()):
        if j % 10 == 0:
            _progress(progress[0] + (progress[1] - progress[0]) * j / max(n, 1))
        img = cv2.imread(r["path"])
        rec = {"idx": i, "night": None, "ok": False, "n_matches": 0, "n_inliers": 0, "score": 0.0,
               "reproj_err_px": np.nan, "method": "", "H": None}
        if img is None or img.shape[:2] != ref.shape[:2]:
            rec["night"] = False if img is not None else None
            rec["method"] = "unreadable" if img is None else "size_mismatch"
            rows.append(rec)
            continue
        rec["night"] = is_night(img, cfg)
        if rec["night"]:
            rows.append(rec)
            continue
        reg, H, used = None, None, ""
        for m in stages:
            reg = regs[m].register(img)
            H, used = reg.H, regs[m].method
            if reg.ok:
                break
        if not reg.ok and last_good is not None and (r["time"] - last_good[0]).total_seconds() <= cfg.chain_hours * 3600:
            if last_good[2] is not None:
                chain.set_reference(last_good[2])
                last_good = (last_good[0], last_good[1], None)
            reg2 = chain.register(img)
            if reg2.ok:
                reg, H, used = reg2, last_good[1] @ reg2.H, chain.method + "-chain"
        rec.update(ok=bool(reg.ok), n_matches=reg.n_matches, n_inliers=reg.n_inliers, score=reg.score,
                   reproj_err_px=reg.reproj_err_px, method=used)
        if reg.ok:
            rec["H"] = H.ravel().tolist()
            last_good = (r["time"], H, img)
        rows.append(rec)
    return pd.DataFrame(rows).set_index("idx")


def accumulate_corr(frames: pd.DataFrame, reg: pd.DataFrame, ref_shape, cfg: Cfg) -> "CorrAccumulator":
    """Cheap pass: warp registered fit-window daytime frames at map scale and accumulate the
    per-pixel appearance↔stage correlation."""
    h, w = ref_shape
    sh, sw = int(h * cfg.map_scale), int(w * cfg.map_scale)
    S = np.diag([cfg.map_scale, cfg.map_scale, 1.0])
    acc = CorrAccumulator()
    sel = reg[reg["ok"]].index
    for i in sel:
        r = frames.loc[i]
        if r["window"] != "fit" or not np.isfinite(r["stage_ft"]):
            continue
        img = cv2.imread(r["path"])
        H = np.array(reg.loc[i, "H"]).reshape(3, 3)
        warped = cv2.warpPerspective(img, S @ H, (sw, sh), flags=cv2.INTER_AREA)
        m = cv2.warpPerspective(np.full(img.shape[:2], 255, np.uint8), S @ H, (sw, sh), flags=cv2.INTER_NEAREST) > 0
        acc.add(appearance_channels(warped, m), m, float(r["stage_ft"]))
    return acc


def thin_frames(frames: pd.DataFrame, min_gap_min: float) -> pd.DataFrame:
    """Keep at most one frame per `min_gap_min` minutes (15-min cameras → 30-min cadence)."""
    keep, last = [], None
    for i, t in frames["time"].items():
        if last is None or (t - last).total_seconds() >= min_gap_min * 60 - 30:
            keep.append(i)
            last = t
    return frames.loc[keep]


def appearance_channels(img: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Brightness-normalized gray + saturation (float16, HxWx2). Per-frame z-scoring removes global
    illumination so that 'storm = dark + high water' does not masquerade as a stage signal."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    s = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[..., 1].astype(np.float32)
    out = []
    for c in (g, s):
        v = c[valid]
        mu, sd = (float(v.mean()), float(v.std()) + 1e-3) if v.size else (0.0, 1.0)
        out.append((c - mu) / sd)
    return np.stack(out, -1).astype(np.float16)


class CorrAccumulator:
    """Streaming per-pixel Pearson correlation between appearance channels and stage."""

    def __init__(self):
        self.n = self.sx = self.sxx = self.sh = self.shh = self.sxh = None
        self.count = 0

    def add(self, x: np.ndarray, valid: np.ndarray, h: float):
        x = x.astype(np.float64) * valid[..., None]
        v = valid[..., None].astype(np.float64)
        if self.n is None:
            z = np.zeros_like(x)
            self.n, self.sx, self.sxx, self.sh, self.shh, self.sxh = (z.copy() for _ in range(6))
        self.n += v
        self.sx += x
        self.sxx += x * x
        self.sh += v * h
        self.shh += v * h * h
        self.sxh += x * h
        self.count += 1

    def corr(self) -> np.ndarray:
        n = np.maximum(self.n, 1)
        num = n * self.sxh - self.sx * self.sh
        den = np.sqrt(np.maximum(n * self.sxx - self.sx ** 2, 0) * np.maximum(n * self.shh - self.sh ** 2, 0))
        return np.where(den > 1e-9, num / np.maximum(den, 1e-9), 0.0)


def correlation_map(acc: CorrAccumulator, cfg: Cfg) -> np.ndarray:
    """max over channels of |Pearson corr(appearance, stage)| per pixel (fit window only)."""
    C = np.abs(acc.corr()).max(-1)
    C[acc.n[..., 0] < 0.9 * acc.count] = 0
    C[: int(cfg.mask_top * cfg.map_scale) + 2] = 0
    return cv2.GaussianBlur(C.astype(np.float32), (5, 5), 0)


def transects_from_map(C: np.ndarray, cfg: Cfg) -> list[Transect]:
    """Bands of high |corr| are where the waterline sweeps; cut across each band (minor PCA axis)."""
    hi = float(np.quantile(C[C > 0], 0.995)) if (C > 0).any() else 0.0
    thr = max(cfg.corr_floor, 0.6 * hi)
    B = ((C >= thr) * 255).astype(np.uint8)
    B = cv2.morphologyEx(B, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(B, connectivity=8)
    comps = []
    for k in range(1, n):
        if stats[k, cv2.CC_STAT_AREA] < 15:
            continue
        comps.append((float(C[lab == k].sum()), k))
    comps.sort(reverse=True)
    H, W = C.shape
    inv = 1.0 / cfg.map_scale
    out: list[Transect] = []
    for ci, (_, k) in enumerate(comps[: cfg.max_components]):
        ys, xs = np.nonzero(lab == k)
        P = np.stack([xs, ys], 1).astype(np.float64)
        w = C[ys, xs].astype(np.float64)
        mu = (P * w[:, None]).sum(0) / w.sum()
        cov = np.cov((P - mu).T, aweights=w)
        evals, evecs = np.linalg.eigh(cov)
        e_major, e_minor = evecs[:, 1], evecs[:, 0]
        proj_major = (P - mu) @ e_major
        proj_minor = (P - mu) @ e_minor
        half = max(2.5 * float(np.sqrt(max(evals[0], 1e-6))) + 6.0, 12.0)
        if np.ptp(proj_minor) > 0:
            half = max(half, 0.75 * float(np.ptp(proj_minor)) + 6.0)
        qs = np.linspace(0.2, 0.8, cfg.transects_per_component) if cfg.transects_per_component > 1 else [0.5]
        for qi, q in enumerate(qs):
            c = mu + float(np.quantile(proj_major, q)) * e_major
            p0, p1 = c - half * e_minor, c + half * e_minor
            p0 = np.clip(p0, [1, cfg.mask_top * cfg.map_scale + 2], [W - 2, H - 2])
            p1 = np.clip(p1, [1, cfg.mask_top * cfg.map_scale + 2], [W - 2, H - 2])
            if np.hypot(*(p1 - p0)) < 10:
                continue
            out.append(Transect(f"c{ci}t{qi}", (np.stack([p0, p1]) * inv).astype(np.float32), cfg.half_width))
    return out


def detect_all(frames: pd.DataFrame, reg: pd.DataFrame, ref_shape, transects: list[Transect], cfg: Cfg,
               progress=(0.5, 0.9)) -> pd.DataFrame:
    """Pass 2: waterline position per (frame, transect, detector) with a temporal prior."""
    rows = []
    prior: dict = {}
    ok = reg[reg["ok"]]
    n = len(ok)
    for j, (i, rr) in enumerate(ok.iterrows()):
        if j % 25 == 0:
            _progress(progress[0] + (progress[1] - progress[0]) * j / max(n, 1))
        r = frames.loc[i]
        img = cv2.imread(r["path"])
        warped = warp_to_reference(img, np.array(rr["H"]).reshape(3, 3), ref_shape)
        for t in transects:
            feats = profile_features(warped, t)
            for det in DETECTORS:
                key = (t.name, det)
                p = prior.get(key)
                ps = p[1] if p is not None and (r["time"] - p[0]).total_seconds() <= cfg.prior_hours * 3600 else None
                if det == "changepoint":
                    s, conf = detect_changepoint(feats, prior_s=ps, prior_sigma=cfg.prior_sigma)
                else:
                    s, conf = detect_transition(feats, prior_s=ps, prior_sigma=cfg.prior_sigma)
                if np.isfinite(s) and conf >= cfg.min_conf:
                    prior[key] = (r["time"], s)
                rows.append({"idx": i, "transect": t.name, "detector": det, "s": s, "conf": conf})
    return pd.DataFrame(rows)


def _clip_h(h, lo, hi):
    span = hi - lo
    return np.clip(h, lo - 0.25 * span - 0.5, hi + 0.25 * span + 0.5)


def weighted_median(v: np.ndarray, w: np.ndarray) -> float:
    o = np.argsort(v)
    v, w = v[o], w[o]
    c = np.cumsum(w)
    return float(v[np.searchsorted(c, 0.5 * c[-1])])


class TransectModel:
    def __init__(self, name, det, proj: ProjectiveModel, iso, weight):
        self.name, self.det, self.proj, self.iso, self.weight = name, det, proj, iso, weight

    def h_proj(self, s):
        return _clip_h(self.proj.h(s), self.proj.h_min, self.proj.h_max)

    def h_iso(self, s):
        hk, uk = self.iso
        o = np.argsort(uk)
        return np.interp(s, uk[o], hk[o])


def fit_models(D: pd.DataFrame, det: str, names: list[str], cfg: Cfg, weights: Optional[dict] = None):
    models = []
    for name in names:
        d = D[(D["transect"] == name) & (D["detector"] == det) & (D["conf"] >= cfg.min_conf)].dropna(
            subset=["s", "stage_ft"])
        if len(d) < 15:
            continue
        try:
            pm = fit_robust(d["stage_ft"].values, d["s"].values, inlier_px=cfg.inlier_px)
        except ValueError:
            continue
        lo, hi = pm.h_min, pm.h_max
        if not np.isfinite(lo) or not pm.is_monotone_over(lo - 0.5, hi + 0.5) or pm.n_inliers < 0.4 * pm.n_total:
            continue
        try:
            iso = fit_isotonic_lookup(d["stage_ft"].values, d["s"].values, n_bins=24)
        except ValueError:
            iso = (np.array([lo, hi]), pm.u(np.array([lo, hi])))
        models.append(TransectModel(name, det, pm, iso, (weights or {}).get(name, 1.0)))
    return models


def predict(D: pd.DataFrame, models: list[TransectModel], kind: str = "proj") -> pd.Series:
    """Fused stage per frame idx (weighted median over transects)."""
    if not models:
        return pd.Series(dtype=float)
    parts = []
    for m in models:
        d = D[(D["transect"] == m.name) & (D["detector"] == m.det)].dropna(subset=["s"])
        d = d[d["conf"] >= 0.05]
        if not len(d):
            continue
        h = m.h_proj(d["s"].values) if kind == "proj" else m.h_iso(d["s"].values)
        parts.append(pd.DataFrame({"idx": d["idx"].values, "h": h, "w": d["conf"].values * m.weight}))
    if not parts:
        return pd.Series(dtype=float)
    P = pd.concat(parts)
    P = P[np.isfinite(P["h"])]
    return P.groupby("idx").apply(lambda g: weighted_median(g["h"].values, g["w"].values + 1e-9),
                                  include_groups=False)


def select(D_fit: pd.DataFrame, transects: list[Transect], cv_split, cfg: Cfg):
    """Blocked CV inside the fit window → (detector, chosen transect names, weights, cv table)."""
    A, B = D_fit[D_fit["time"] < cv_split], D_fit[D_fit["time"] >= cv_split]
    names = [t.name for t in transects]
    table, best = [], None
    for det in DETECTORS:
        ms = fit_models(A, det, names, cfg)
        per = {}
        for m in ms:
            pB = predict(B, [m])
            gB = B.drop_duplicates("idx").set_index("idx")["stage_ft"]
            j = pd.concat([pB.rename("p"), gB.rename("g")], axis=1).dropna()
            if len(j) >= 5:
                per[m.name] = float((j["p"] - j["g"]).abs().mean())
                table.append({"detector": det, "transect": m.name, "cv_mae_ft": per[m.name], "cv_n": len(j),
                              "px_per_ft": float(abs(m.proj.du_dh(np.median(A["stage_ft"].dropna()))))})
        keep = [n for n, e in per.items() if e <= cfg.max_cv_mae_ft]
        if per and not keep:
            keep = [min(per, key=per.get)]
        if not keep:
            continue
        # keep transects within 2x of the best one, weight by inverse CV error
        bmin = min(per[n] for n in keep)
        keep = [n for n in keep if per[n] <= max(2 * bmin, bmin + 0.05)]
        weights = {n: 1.0 / (per[n] + 0.05) for n in keep}
        fused = predict(B, [m for m in ms if m.name in keep])
        gB = B.drop_duplicates("idx").set_index("idx")["stage_ft"]
        j = pd.concat([fused.rename("p"), gB.rename("g")], axis=1).dropna()
        if not len(j):
            continue
        mae = float((j["p"] - j["g"]).abs().mean())
        cov = len(j) / max(len(gB.dropna()), 1)
        table.append({"detector": det, "transect": "FUSED", "cv_mae_ft": mae, "cv_n": len(j), "cv_coverage": cov})
        if best is None or mae < best[0]:
            best = (mae, det, keep, weights)
    return best, pd.DataFrame(table)


def persistence_24h(times: pd.Series, stage: pd.DataFrame) -> pd.Series:
    s = stage[["time", "value"]].dropna().sort_values("time")
    q = pd.DataFrame({"t": times.values - pd.Timedelta(hours=24), "idx": times.index}).sort_values("t")
    m = pd.merge_asof(q, s, left_on="t", right_on="time", direction="backward", tolerance=pd.Timedelta(hours=1))
    return m.set_index("idx")["value"]


def metrics(pred: pd.Series, gauge: pd.Series) -> dict:
    j = pd.concat([pred.rename("p"), gauge.rename("g")], axis=1).dropna()
    if not len(j):
        return {"n": 0, "MAE_ft": np.nan, "RMSE_ft": np.nan, "pct_within_0.1": np.nan, "pct_within_0.25": np.nan}
    e = (j["p"] - j["g"]).abs()
    return {"n": int(len(j)), "MAE_ft": float(e.mean()), "RMSE_ft": float(np.sqrt((e ** 2).mean())),
            "pct_within_0.1": float((e <= 0.1).mean() * 100), "pct_within_0.25": float((e <= 0.25).mean() * 100)}


# ---------------------------------------------------------------- drawing (cv2 only)
def draw_overlay(warped: np.ndarray, transects, Dframe: pd.DataFrame, det: str, chosen, title: str) -> np.ndarray:
    img = warped.copy()
    for t in transects:
        pts = t.points.astype(np.int32)
        col = (0, 255, 255) if t.name in chosen else (120, 120, 120)
        cv2.polylines(img, [pts], False, col, 1, cv2.LINE_AA)
        d = Dframe[(Dframe["transect"] == t.name) & (Dframe["detector"] == det)]
        if len(d) and np.isfinite(d["s"].iloc[0]):
            s_, xy = t.sample_points()
            k = int(np.clip(np.searchsorted(s_, d["s"].iloc[0]), 0, len(xy) - 1))
            cv2.circle(img, tuple(int(v) for v in xy[k]), 5, (0, 0, 255) if t.name in chosen else (200, 200, 200), 2,
                       cv2.LINE_AA)
    cv2.rectangle(img, (0, img.shape[0] - 26), (img.shape[1], img.shape[0]), (0, 0, 0), -1)
    cv2.putText(img, title, (6, img.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def draw_timeseries(stage: pd.DataFrame, pred: pd.Series, times: pd.Series, t0, t_split, t1, title: str,
                    W: int = 1100, H: int = 360) -> np.ndarray:
    img = np.full((H, W, 3), 255, np.uint8)
    L, R, T, B = 60, 15, 30, 40
    st = stage[(stage["time"] >= t0) & (stage["time"] <= t1)]
    pv = pred.dropna()
    ys = np.concatenate([st["value"].values, pv.values]) if len(pv) else st["value"].values
    lo, hi = np.nanquantile(ys, 0.005), np.nanquantile(ys, 0.995)
    pad = 0.1 * max(hi - lo, 0.2)
    lo, hi = lo - pad, hi + pad
    span = (t1 - t0).total_seconds()
    X = lambda t: int(L + (W - L - R) * (pd.Timestamp(t) - t0).total_seconds() / span)
    Y = lambda v: int(H - B - (H - T - B) * (v - lo) / (hi - lo))
    for k in range(6):
        v = lo + (hi - lo) * k / 5
        cv2.line(img, (L, Y(v)), (W - R, Y(v)), (230, 230, 230), 1)
        cv2.putText(img, f"{v:.2f}", (4, Y(v) + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (80, 80, 80), 1, cv2.LINE_AA)
    xs = X(t_split)
    cv2.line(img, (xs, T), (xs, H - B), (0, 0, 0), 1)
    cv2.putText(img, "fit | test", (xs - 32, T - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    pts = np.array([[X(t), Y(v)] for t, v in zip(st["time"], st["value"])], np.int32)
    if len(pts) > 1:
        cv2.polylines(img, [pts], False, (40, 40, 40), 1, cv2.LINE_AA)
    for idx, v in pv.items():
        x, y = X(times.loc[idx]), Y(np.clip(v, lo, hi))
        cv2.circle(img, (x, y), 2, (0, 90, 230) if times.loc[idx] >= t_split else (230, 140, 0), -1, cv2.LINE_AA)
    cv2.putText(img, title, (L, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(img, "gauge (line) / camera fit-window (orange) / camera test (blue), ft", (L, H - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (60, 60, 60), 1, cv2.LINE_AA)
    return img


def run_site(cam_id: str, data_dir: Path, out_dir: Path, t0, t_split, t1, cfg: Cfg = Cfg(),
             score_test: bool = True) -> SiteResult:
    """score_test=False (development): only fit-window CV numbers are produced; test days are never scored."""
    tic = time.time()
    res = SiteResult(cam_id)
    d = data_dir / "derived" / cam_id
    frames = pd.read_parquet(d / "frames.parquet")
    stage = pd.read_parquet(d / "stage.parquet")
    frames = frames[(frames["time"] >= t0) & (frames["time"] < t1)].sort_values("time").reset_index(drop=True)
    frames = thin_frames(frames, cfg.min_gap_min).reset_index(drop=True)
    frames["window"] = np.where(frames["time"] < t_split, "fit", "test")
    out_dir.mkdir(parents=True, exist_ok=True)

    ref_i, ref = choose_reference(frames, cfg)
    res.notes.append(f"reference {frames.loc[ref_i, 'filename']} stage {frames.loc[ref_i, 'stage_ft']:.2f} ft")
    cache = d / f"registration_{cfg.reg_method}.parquet"
    ref_name = frames.loc[ref_i, "filename"]
    cached = pd.read_parquet(cache) if cache.exists() else None
    if cached is not None and (cached["ref"] == ref_name).all() and set(frames["filename"]) <= set(cached["filename"]):
        reg = (frames[["filename"]].reset_index().merge(cached.drop(columns="ref"), on="filename")
               .set_index("index").drop(columns="filename"))
        reg.index.name = "idx"
    else:
        reg = register_frames(frames, ref, cfg, cfg.reg_method)
        reg.join(frames["filename"]).assign(ref=ref_name).reset_index(drop=True).to_parquet(cache)
    acc = accumulate_corr(frames, reg, ref.shape[:2], cfg)
    F = frames.join(reg)
    day = F[F["night"] == False]  # noqa: E712
    if acc.count < 30:
        res.notes.append(f"only {acc.count} registered fit-window day frames with stage; skipped")
        res.metrics = _site_metrics(F, day, None, None, None, None, None)
        return res
    C = correlation_map(acc, cfg)
    cm = cv2.applyColorMap((np.clip(C / max(C.max(), 1e-6), 0, 1) * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
    transects = transects_from_map(C, cfg)
    res.transects = [{"name": t.name, "points": t.points.tolist()} for t in transects]
    ref_vis = ref.copy()
    for t in transects:
        cv2.polylines(ref_vis, [t.points.astype(np.int32)], False, (0, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(ref_vis, t.name, tuple(int(v) for v in t.points[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                    (0, 255, 255), 1, cv2.LINE_AA)
    cm_full = cv2.resize(cm, (ref.shape[1], ref.shape[0]), interpolation=cv2.INTER_NEAREST)
    cv2.imwrite(str(out_dir / "corrmap.jpg"), np.hstack([ref_vis, cm_full]), [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not transects:
        res.notes.append("no stage-correlated band found → no transects")
        res.metrics = _site_metrics(F, day, None, None, None, None, None)
        return res

    D = detect_all(frames, reg, ref.shape[:2], transects, cfg)
    D = D.merge(frames[["time", "stage_ft", "window"]], left_on="idx", right_index=True)
    D.to_parquet(data_dir / "derived" / cam_id / "detections.parquet", index=False)
    D_fit, D_test = D[D["window"] == "fit"], D[D["window"] == "test"]
    cv_split = t_split - pd.Timedelta(days=cfg.cv_days)
    best, cvt = select(D_fit, transects, cv_split, cfg)
    cvt.to_csv(out_dir / "cv_selection.csv", index=False)
    if best is None:
        res.notes.append("no transect produced a valid projective fit on the fit window")
        res.metrics = _site_metrics(F, day, None, None, None, None, None)
        return res
    _, det, keep, weights = best
    models = fit_models(D_fit, det, keep, cfg, weights)
    res.notes.append(f"detector={det}, transects={keep}")
    fused_cv = cvt[(cvt["transect"] == "FUSED") & (cvt["detector"] == det)].iloc[0]
    res.metrics.update({"cv_mae_ft": float(fused_cv["cv_mae_ft"]), "cv_coverage": float(fused_cv["cv_coverage"]),
                        "reg_rate": float(day["ok"].mean()), "n_day": int(len(day))})
    if not score_test:
        return res
    times = frames["time"]
    p_all = predict(D, models, "proj")
    iso_all = predict(D, models, "iso")
    pers = persistence_24h(times, stage)
    pd.DataFrame({"time": times, "gauge_ft": frames["stage_ft"], "window": frames["window"],
                  "camera_ft": p_all.reindex(frames.index), "isotonic_ft": iso_all.reindex(frames.index),
                  "persistence24_ft": pers.reindex(frames.index)}).to_parquet(d / "readings.parquet")
    res.metrics = _site_metrics(F, day, p_all, iso_all, pers, models, D_fit)
    res.metrics["detector"] = det
    res.metrics["n_transects_used"] = len(models)
    res.metrics["n_transects_found"] = len(transects)

    ts = draw_timeseries(stage, p_all, times, t0, t_split, t1,
                         f"{cam_id}  test MAE {res.metrics['MAE_ft']:.3f} ft, coverage {res.metrics['coverage']:.0%}")
    cv2.imwrite(str(out_dir / "timeseries.png"), ts)
    # two overlays: test frames at the highest and lowest gauge stage that have a reading
    tt = F[(F["window"] == "test") & F["ok"] & F.index.isin(p_all.index)].dropna(subset=["stage_ft"])
    picks = [] if not len(tt) else list(dict.fromkeys([tt["stage_ft"].idxmax(), tt["stage_ft"].idxmin()]))
    for k, i in enumerate(picks, 1):
        img = cv2.imread(frames.loc[i, "path"])
        warped = warp_to_reference(img, np.array(F.loc[i, "H"]).reshape(3, 3), ref.shape[:2])
        title = (f"{frames.loc[i, 'time']:%Y-%m-%d %H:%M}Z  gauge {frames.loc[i, 'stage_ft']:.2f} ft  "
                 f"camera {p_all.loc[i]:.2f} ft")
        ov = draw_overlay(warped, transects, D[D["idx"] == i], det, keep, title)
        cv2.imwrite(str(out_dir / f"overlay_{k}.jpg"), ov, [cv2.IMWRITE_JPEG_QUALITY, 85])
    res.metrics["runtime_s"] = round(time.time() - tic, 1)
    (out_dir / "site.json").write_text(json.dumps(asdict(res), indent=1, default=str))
    _progress(1.0)
    return res


def _site_metrics(F, day, p_all, iso_all, pers, models, D_fit) -> dict:
    test_day = day[day["window"] == "test"]
    gauge_test = test_day["stage_ft"].dropna()
    m = {"n_frames": int(len(F)), "n_night": int((F["night"] == True).sum()),  # noqa: E712
         "n_day": int(len(day)), "n_day_registered": int(day["ok"].sum()),
         "reg_rate": float(day["ok"].mean()) if len(day) else np.nan,
         "n_test_day": int(len(test_day)),
         "n_reg_orb": int((day["ok"] & (day["method"] == "orb")).sum()),
         "n_reg_aliked": int((day["ok"] & (day["method"] == "aliked+lightglue")).sum()),
         "n_reg_chain": int((day["ok"] & day["method"].str.endswith("-chain")).sum()),
         "stage_range_ft": float(F["stage_ft"].max() - F["stage_ft"].min()) if F["stage_ft"].notna().any() else np.nan,
         "test_stage_range_ft": float(gauge_test.max() - gauge_test.min()) if len(gauge_test) else np.nan}
    if p_all is None:
        m.update({"coverage": 0.0, "MAE_ft": np.nan})
        return m
    pt = p_all.reindex(gauge_test.index)
    m.update(metrics(pt, gauge_test))
    m["coverage"] = float(pt.notna().mean()) if len(gauge_test) else 0.0
    covered = pt.dropna().index
    m["MAE_isotonic_ft"] = metrics(iso_all.reindex(covered), gauge_test.reindex(covered))["MAE_ft"]
    m["MAE_persist24_ft"] = metrics(pers.reindex(covered), gauge_test.reindex(covered))["MAE_ft"]
    m["MAE_persist24_all_ft"] = metrics(pers.reindex(gauge_test.index), gauge_test)["MAE_ft"]
    med_h = float(D_fit["stage_ft"].median())
    m["px_per_ft"] = float(np.median([abs(x.proj.du_dh(med_h)) for x in models]))
    return m
