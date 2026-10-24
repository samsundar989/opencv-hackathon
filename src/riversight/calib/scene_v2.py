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
