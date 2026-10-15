"""Scene regressor: block features → stage ± σ (the primary estimator, D-0006).

    registered frame → block features → flood-height-map ROI → kernel ridge → causal smoothing → stage ± σ

Kernel ridge with a linear kernel on standardised features, solved in the dual (n frames ≪ 18,000
features). The ROI is the set of blocks the flood-height map marks reliable (balanced accuracy ≥ 0.85),
fitted on the training frames only; with fewer than 50 ROI blocks the model falls back to all blocks.

σ comes from out-of-fold residuals of blocked (contiguous-time) folds inside the training data, so it is
an honest per-site error scale rather than a training residual.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from riversight.calib.flood_height_map import FloodHeightMap, fit_thr


def kernel_ridge(Xtr: np.ndarray, ytr: np.ndarray, Xte: np.ndarray, lam: float = 1.0) -> np.ndarray:
    """Linear-kernel ridge in the dual on standardised features (reference: Cowork model.py `ridge`)."""
    A = Xtr.reshape(len(Xtr), -1).astype(np.float32)
    Bm = Xte.reshape(len(Xte), -1).astype(np.float32)
    mu = A.mean(0)
    sd = A.std(0) + 1e-3
    A = (A - mu) / sd
    Bm = (Bm - mu) / sd
    D = A.shape[1]
    K = (A @ A.T).astype(np.float64) / D
    Kb = (Bm @ A.T).astype(np.float64) / D
    ym = float(ytr.mean())
    alpha = np.linalg.solve(K + lam * 0.05 * np.eye(len(K)), ytr - ym)
    return Kb @ alpha + ym


def blocked_folds(n: int, k: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """k contiguous folds over n time-ordered samples (train = the rest)."""
    edges = np.linspace(0, n, k + 1).astype(int)
    out = []
    for i in range(k):
        te = np.zeros(n, bool)
        te[edges[i]:edges[i + 1]] = True
        out.append((~te, te))
    return out


@dataclass
class SceneRegressor:
    lam: float = 1.0
    min_acc: float = 0.85
    min_roi: int = 50
    use_roi: bool = True
    sigma_folds: int = 0          # >1 → estimate σ from blocked out-of-fold residuals at fit time
    fhm: FloodHeightMap | None = None
    roi: np.ndarray | None = None
    sigma: float = float("nan")
    _Xtr: np.ndarray | None = field(default=None, repr=False)
    _ytr: np.ndarray | None = field(default=None, repr=False)

    def select_roi(self, M: FloodHeightMap) -> np.ndarray:
        sel = M.reliable(self.min_acc)
        if not self.use_roi or sel.sum() < self.min_roi:
            return np.ones_like(sel)
        return sel

    def fit(self, X: np.ndarray, h: np.ndarray) -> "SceneRegressor":
        """X (n, B, d) time-ordered training features, h (n,) gauge stage."""
        self.fhm = fit_thr(X, h)
        self.roi = self.select_roi(self.fhm)
        self._Xtr, self._ytr = X[:, self.roi], np.asarray(h, float)
        if self.sigma_folds > 1:
            res = []
            for tr, te in blocked_folds(len(h), self.sigma_folds):
                sub = SceneRegressor(self.lam, self.min_acc, self.min_roi, self.use_roi).fit(X[tr], h[tr])
                res.append(sub.predict(X[te]) - h[te])
            self.sigma = float(np.std(np.concatenate(res)))
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self._Xtr is None:
            raise RuntimeError("fit() first")
        return kernel_ridge(self._Xtr, self._ytr, X[:, self.roi], self.lam)

    @property
    def n_roi(self) -> int:
        return int(self.roi.sum()) if self.roi is not None else 0


# ---- causal smoothing -------------------------------------------------------------------------------

def causal_median(t: pd.DatetimeIndex, p: np.ndarray, window: str = "3h") -> np.ndarray:
    """Trailing rolling median over `window` (uses only the current and earlier frames)."""
    return pd.Series(p, index=pd.DatetimeIndex(t)).rolling(window, min_periods=1).median().values


def kalman_1d(t: pd.DatetimeIndex, z: np.ndarray, q_per_h: float, r: float) -> tuple[np.ndarray, np.ndarray]:
    """Causal random-walk Kalman filter on irregular times. q_per_h: process variance per hour (ft²/h);
    r: measurement variance (ft²). Overnight gaps inflate the prior, so morning frames re-anchor fast.
    Returns (filtered state, filtered σ)."""
    t = pd.DatetimeIndex(t)
    hrs = (t - t[0]).total_seconds().values / 3600.0
    x, P = np.nan, np.inf
    xs, ss = np.full(len(z), np.nan), np.full(len(z), np.nan)
    last = None
    for i, zi in enumerate(z):
        if last is not None and np.isfinite(x):
            P = P + q_per_h * max(hrs[i] - hrs[last], 0.0)
        if np.isfinite(zi):
            if not np.isfinite(x):
                x, P = zi, r
            else:
                K = P / (P + r)
                x, P = x + K * (zi - x), (1 - K) * P
        xs[i], ss[i] = x, np.sqrt(P) if np.isfinite(P) else np.nan
        last = i
    return xs, ss


def kalman_params(t_gauge: pd.DatetimeIndex, h_gauge: np.ndarray, residuals: np.ndarray) -> tuple[float, float]:
    """q from the gauge's own hourly increments; r from the white (non-autocorrelated) part of the
    out-of-fold residuals, r = var(e)·(1 − ρ₁) with ρ₁ the lag-1 autocorrelation of consecutive frames."""
    s = pd.Series(np.asarray(h_gauge, float), index=pd.DatetimeIndex(t_gauge)).dropna()
    hourly = s.resample("1h").median().dropna()
    dh = np.diff(hourly.values)
    q = float(np.var(dh)) if len(dh) > 2 else 1e-3
    e = np.asarray(residuals, float)
    e = e[np.isfinite(e)]
    if len(e) < 4:
        return max(q, 1e-6), 0.05
    rho = float(np.corrcoef(e[:-1], e[1:])[0, 1]) if np.std(e) > 0 else 0.0
    r = float(np.var(e)) * (1 - np.clip(rho, 0.0, 0.95))
    return max(q, 1e-6), max(r, 1e-6)
