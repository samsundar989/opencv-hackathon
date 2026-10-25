"""Scene model v2 (candidate, W4 / D-0010 §2): v1 block features ‖ DINOv2 patch tokens, plus seasonal terms.

    v1:  ROI block features (D-0007)                      → K₁ = A₁A₁ᵀ / D₁
    v2:  + DINOv2 patch tokens (cv2.dnn, fixed PCA)       → K₂ = A₂A₂ᵀ / D₂ over the DINO ROI
         K = (1 − w)·K₁ + w·K₂, kernel ridge (λ as D-0007), causal Kalman (as D-0007)

Each kernel is a linear kernel on standardised features divided by its dimension, so a weighted sum is
still a linear kernel on [√((1−w)/D₁)·A₁ ‖ √(w/D₂)·A₂]: the live bundle stays one primal weight vector.

Ingredients (each one an ablation in scripts/v2_cv.py):
  * DINO-space reliability: the flood-height map fitted on DINO patches (`fit_thr` on (n, 448, K)) picks the
    patches whose tokens split wet from dry; `dino_v1roi` instead takes the patches under v1's ROI blocks.
  * (a) sun / season nuisance: the training fit's leave-one-out residuals are regressed on solar elevation,
    azimuth (and optionally day of year); the fitted bias is added to the raw prediction before the Kalman.
  * (b) per-frame scene-mean removal of DINO tokens (global appearance: foliage, haze, white balance).
  * (c) recency weighting of training samples, wᵢ = exp(−ageᵢ / τ).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---- solar position (NOAA approximation, ~0.5° — plenty for a nuisance covariate) ---------------------

def solar_position(t: pd.DatetimeIndex, lat: float, lng: float) -> tuple[np.ndarray, np.ndarray]:
    """(elevation°, azimuth° clockwise from north) of the sun at UTC times t."""
    t = pd.DatetimeIndex(t).tz_convert("UTC")
    doy = t.dayofyear.values.astype(float)
    hr = t.hour.values + t.minute.values / 60 + t.second.values / 3600
    g = 2 * np.pi / 365 * (doy - 1 + (hr - 12) / 24)
    eqt = 229.18 * (0.000075 + 0.001868 * np.cos(g) - 0.032077 * np.sin(g) - 0.014615 * np.cos(2 * g)
                    - 0.040849 * np.sin(2 * g))
    decl = (0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g) - 0.006758 * np.cos(2 * g)
            + 0.000907 * np.sin(2 * g) - 0.002697 * np.cos(3 * g) + 0.00148 * np.sin(3 * g))
    tst = hr * 60 + eqt + 4 * lng
    ha = np.radians(tst / 4 - 180)
    la = np.radians(lat)
    cz = np.clip(np.sin(la) * np.sin(decl) + np.cos(la) * np.cos(decl) * np.cos(ha), -1, 1)
    zen = np.arccos(cz)
    az = np.degrees(np.arctan2(np.sin(ha), np.cos(ha) * np.sin(la) - np.tan(decl) * np.cos(la))) + 180
    return 90 - np.degrees(zen), az % 360


def nuisance_matrix(t: pd.DatetimeIndex, lat: float, lng: float, doy: bool = False) -> np.ndarray:
    """(n, 3|5): sun elevation, sin/cos azimuth [, sin/cos day of year]."""
    el, az = solar_position(t, lat, lng)
    cols = [el, np.sin(np.radians(az)), np.cos(np.radians(az))]
    if doy:
        d = 2 * np.pi * pd.DatetimeIndex(t).dayofyear.values / 365.25
        cols += [np.sin(d), np.cos(d)]
    return np.stack(cols, 1)


# ---- features ---------------------------------------------------------------------------------------

def standardise(A_tr: np.ndarray, A_te: np.ndarray, eps: float = 1e-3):
    mu = A_tr.mean(0)
    sd = A_tr.std(0) + eps
    return (A_tr - mu) / sd, (A_te - mu) / sd, mu, sd


def scene_mean_removed(P: np.ndarray) -> np.ndarray:
    """(n, patches, k) projected tokens minus each frame's mean over patches (ingredient b). Exact in the
    projected space because the PCA projection is affine."""
    return P - P.mean(1, keepdims=True)


def linear_kernel(A_tr: np.ndarray, A_te: np.ndarray):
    """Standardise on train, (K_tr, K_te) = (AAᵀ/D, BAᵀ/D) in float64."""
    A, B, _, _ = standardise(A_tr.astype(np.float32), A_te.astype(np.float32))
    D = A.shape[1]
    return (A @ A.T).astype(np.float64) / D, (B @ A.T).astype(np.float64) / D


# ---- kernel ridge with sample weights and LOO residuals --------------------------------------------

def ridge_dual(K: np.ndarray, Kb: np.ndarray, y: np.ndarray, lam: float = 1.0,
               sw: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Kernel ridge (D-0007 scaling c = 0.05·λ) with optional sample weights sw.

    minimise Σ swᵢ (yᵢ − f(xᵢ))² + c‖f‖²  →  α = (K + c·diag(1/sw))⁻¹ (y − ȳ_w).
    LOO residual eᵢ = αᵢ / [(K + Λ)⁻¹]ᵢᵢ (holds for any diagonal Λ). Returns (test predictions, loo)."""
    c = lam * 0.05
    if sw is None:
        e, V = np.linalg.eigh(K)
        ym = float(y.mean())
        inv = 1.0 / (e + c)
        alpha = V @ (inv * (V.T @ (y - ym)))
        loo = alpha / ((V ** 2) @ inv)
        return Kb @ alpha + ym, loo
    sw = np.asarray(sw, float)
    ym = float(np.sum(sw * y) / np.sum(sw))
    Ainv = np.linalg.inv(K + np.diag(c / sw))
    alpha = Ainv @ (y - ym)
    return Kb @ alpha + ym, alpha / np.diag(Ainv)


def recency_weights(t: pd.DatetimeIndex, tau_days: float) -> np.ndarray:
    age = (t[-1] - pd.DatetimeIndex(t)).total_seconds().values / 86400.0
    return np.exp(-age / tau_days)


def nuisance_fit(Z_tr: np.ndarray, loo: np.ndarray, Z_te: np.ndarray, lam: float = 1.0) -> np.ndarray:
    """Ridge of the LOO residuals (y − ŷ₋ᵢ) on standardised nuisance covariates; returns the bias to ADD
    to the test predictions. LOO residuals are honest (each one excludes its own frame)."""
    A, B, _, _ = standardise(Z_tr, Z_te, 1e-6)
    e = np.asarray(loo, float)
    em = e.mean()
    beta = np.linalg.solve(A.T @ A + lam * np.eye(A.shape[1]), A.T @ (e - em))
    return B @ beta + em


def kalman_r(loo: np.ndarray) -> float:
    rho = np.corrcoef(loo[:-1], loo[1:])[0, 1]
    return max(float(np.var(loo)) * (1 - np.clip(rho, 0, 0.95)), 1e-6)


# ---- configuration strings (scripts/v2_cv.py CONFIGS) ------------------------------------------------

def parse_config(cfg: str) -> dict:
    """'v1+dino_roi+norm@0.5+sun+rec120' → kernels, weight, ingredients."""
    parts = cfg.split("+")
    d = {"v1": "v1" in parts, "dino": None, "w": 1.0, "norm": False, "sun": None, "tau": None}
    for p in parts:
        name, _, w = p.partition("@")
        if name.startswith("dino_") or name == "gmean":
            d["dino"] = name
        if name == "norm":
            d["norm"] = True
        if name in ("sun", "sundoy"):
            d["sun"] = name
        if name.startswith("rec"):
            d["tau"] = float(name[3:])
        if w:
            d["w"] = float(w)
    if not d["v1"]:
        d["w"] = 1.0
    elif d["dino"] is None:
        d["w"] = 0.0
    return d



# ---- live shadow bundle (primal form) -----------------------------------------------------------------

def fit_bundle(X: np.ndarray, P: np.ndarray, t: pd.DatetimeIndex, h: np.ndarray, spec: dict, lat: float,
               lng: float, q: float, thr: float = 0.80, lam: float = 1.0, min_roi: int = 50,
               min_dino_roi: int = 10) -> dict:
    """Fit one v2 configuration (`scripts/v2_cv.parse` spec) on time-ordered training data and return the
    primal arrays of scene_model_v2.npz. X (n, 3600, 5) v1 block features, P (n, 448, k) projected tokens."""
    from riversight.calib.flood_height_map import fit_thr
    X = X.astype(np.float32, copy=False)
    P = P.astype(np.float32, copy=False)
    if spec["norm"]:
        P = scene_mean_removed(P)
    n, out, blocks = len(h), {}, []
    M = fit_thr(X, h)
    roi = M.acc >= thr
    if roi.sum() < min_roi:
        roi = np.ones_like(roi)
    out.update(roi=roi, fhm_acc=M.acc, fhm_thr=M.thr, fhm_w=M.w, fhm_mid=M.mid, min_acc=np.float64(thr))
    if spec["v1"] and spec["w"] < 1:
        blocks.append(("v1", X[:, roi].reshape(n, -1), 1 - spec["w"]))
    if spec["dino"] == "dino_roi":
        Md = fit_thr(P, h)
        droi = Md.acc >= thr
        if droi.sum() < min_dino_roi:
            droi = np.ones_like(droi)
        out.update(dino_roi=droi, dino_acc=Md.acc, dino_thr=Md.thr)
        blocks.append(("dino", P[:, droi].reshape(n, -1), spec["w"]))
    elif spec["dino"] is not None:
        raise ValueError(f"shadow bundle supports dino_roi only, got {spec['dino']}")
    A_parts = []
    for name, A, wt in blocks:
        mu, sd = A.mean(0), A.std(0) + 1e-3
        scale = np.sqrt(wt / A.shape[1])
        out[f"mu_{name}"], out[f"sd_{name}"], out[f"scale_{name}"] = mu.astype(np.float32), sd.astype(np.float32), np.float64(scale)
        A_parts.append(((A - mu) / sd * scale).astype(np.float32))
    A = np.concatenate(A_parts, 1)
    Kk = (A @ A.T).astype(np.float64)
    sw = recency_weights(t, spec["tau"]) if spec["tau"] else None
    c = lam * 0.05
    if sw is None:
        ym = float(h.mean())
        Ainv = np.linalg.inv(Kk + c * np.eye(n))
    else:
        ym = float(np.sum(sw * h) / np.sum(sw))
        Ainv = np.linalg.inv(Kk + np.diag(c / sw))
    alpha = Ainv @ (h - ym)
    loo = alpha / np.diag(Ainv)
    out["w"] = (A.T.astype(np.float64) @ alpha)
    out["ym"] = np.float64(ym)
    if spec["sun"]:
        Z = nuisance_matrix(t, lat, lng, spec["sun"] == "sundoy")
        zmu, zsd = Z.mean(0), Z.std(0) + 1e-6
        Az = (Z - zmu) / zsd
        em = float(loo.mean())
        beta = np.linalg.solve(Az.T @ Az + np.eye(Az.shape[1]), Az.T @ (loo - em))
        out.update(z_mu=zmu, z_sd=zsd, z_beta=beta, z_em=np.float64(em), z_doy=np.bool_(spec["sun"] == "sundoy"))
        loo = loo - (Az @ beta + em)
    out["q"], out["r"] = np.float64(q), np.float64(kalman_r(loo))
    out["norm"] = np.bool_(spec["norm"])
    return out


class ShadowV2:
    """Load models/sites_v2/<cam>/ and predict one registered frame (v1 block features + DINO tokens)."""

    def __init__(self, d):
        import json
        from pathlib import Path
        self.dir = Path(d)
        self.meta = json.loads((self.dir / "meta_v2.json").read_text(encoding="utf-8"))
        z = np.load(self.dir / "scene_model_v2.npz")
        self.a = {k: z[k] for k in z.files}
        self.roi = self.a["roi"].astype(bool)
        self.lat, self.lng = self.meta["lat"], self.meta["lon"]

    def needs_dino(self) -> bool:
        return "dino_roi" in self.a

    def predict_raw(self, F: np.ndarray, P: np.ndarray | None, t_utc) -> float:
        """F (3600, 5) v1 block features; P (448, k) projected DINO tokens (None if not needed); t_utc a
        timezone-aware timestamp. Returns the raw (unsmoothed) stage in ft."""
        a, parts = self.a, []
        if "mu_v1" in a:
            parts.append(((F[self.roi].reshape(-1) - a["mu_v1"]) / a["sd_v1"]) * float(a["scale_v1"]))
        if "mu_dino" in a:
            P = P.astype(np.float32)
            if bool(a["norm"]):
                P = P - P.mean(0, keepdims=True)
            parts.append(((P[a["dino_roi"].astype(bool)].reshape(-1) - a["mu_dino"]) / a["sd_dino"]) * float(a["scale_dino"]))
        y = float(np.concatenate(parts).astype(np.float64) @ a["w"] + float(a["ym"]))
        if "z_beta" in a:
            Z = nuisance_matrix(pd.DatetimeIndex([pd.Timestamp(t_utc)]), self.lat, self.lng, bool(a["z_doy"]))
            y += float((((Z - a["z_mu"]) / a["z_sd"]) @ a["z_beta"])[0] + float(a["z_em"]))
        return y

    def kalman_step(self, s, t_unix: float, z: float):
        """Same random-walk step as live.bundle.SiteModel.kalman_step, with this bundle's q and r."""
        from riversight.live.bundle import KalmanState
        x, Pv = s.x, s.P
        if s.t is not None and np.isfinite(x):
            Pv = Pv + float(self.a["q"]) * max((t_unix - s.t) / 3600.0, 0.0)
        r = float(self.a["r"])
        if np.isfinite(z):
            if not np.isfinite(x):
                x, Pv = z, r
            else:
                K = Pv / (Pv + r)
                x, Pv = x + K * (z - x), (1 - K) * Pv
        return KalmanState(x, Pv, t_unix), x, (np.sqrt(Pv) if np.isfinite(Pv) else float("nan"))
