"""Fused "RiverSight stage": gauge when fresh, camera-driven Kalman when the gauge is stale (W4, D-0013 W4-2).

One random-walk Kalman filter over stage:
  * a fresh gauge reading resets the state: x = gauge, P = R_GAUGE (USGS stage resolution ~0.01 ft);
  * between readings the variance grows with the gauge's own hourly-increment variance q (D-0007 Kalman q);
  * a camera reading z enters as z − b with noise r, where b is the camera−gauge offset measured while
    both were available (median over the last BIAS_WINDOW before the gauge went stale) and r is the
    site's camera noise (var of out-of-fold raw residuals × (1 − ρ₁), the D-0007 r).

So during a gauge outage the estimate starts at the last gauge value, follows the camera's *changes*
(the anchored offset removes the camera's slow seasonal bias), and its σ grows overnight when there are
no frames. With no camera it degrades to last-known value with a growing σ. W1 shows `x`, `sigma` and the
provenance ("gauge" / "camera gap-fill"); OUT_OF_RANGE handling (lower bound) stays in the live cycle.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

R_GAUGE = 0.01 ** 2
BIAS_WINDOW = pd.Timedelta("48h")
MIN_BIAS_FRAMES = 3


@dataclass
class Fused:
    x: float = float("nan")
    P: float = float("inf")
    t: float | None = None          # unix seconds of the last update
    b: float = 0.0                  # camera − gauge offset anchored at the last fresh gauge
    source: str = "none"            # "gauge" | "camera gap-fill" | "last gauge"

    @property
    def sigma(self) -> float:
        return float(np.sqrt(self.P)) if np.isfinite(self.P) else float("nan")

    def predict(self, t: float, q_per_h: float) -> "Fused":
        if self.t is not None and np.isfinite(self.x):
            self.P = self.P + q_per_h * max((t - self.t) / 3600.0, 0.0)
            if self.source == "gauge":
                self.source = "last gauge"
        self.t = t
        return self

    def gauge(self, t: float, g: float) -> "Fused":
        self.x, self.P, self.t, self.source = float(g), R_GAUGE, t, "gauge"
        return self

    def camera(self, t: float, z: float, r: float, q_per_h: float) -> "Fused":
        self.predict(t, q_per_h)
        if not np.isfinite(z):
            return self
        z = z - self.b
        if not np.isfinite(self.x):
            self.x, self.P = z, r
        else:
            K = self.P / (self.P + r)
            self.x, self.P = self.x + K * (z - self.x), (1 - K) * self.P
        self.source = "camera gap-fill"
        return self


def anchor_bias(t_cam: pd.DatetimeIndex, z_cam: np.ndarray, h_cam: np.ndarray, t0: pd.Timestamp) -> float:
    """Median camera − gauge over frames in [t0 − BIAS_WINDOW, t0) with both values; 0 if too few."""
    t_cam = pd.DatetimeIndex(t_cam)
    m = (t_cam >= t0 - BIAS_WINDOW) & (t_cam < t0) & np.isfinite(z_cam) & np.isfinite(h_cam)
    return float(np.median(z_cam[m] - h_cam[m])) if m.sum() >= MIN_BIAS_FRAMES else 0.0


def camera_r(resid: np.ndarray) -> float:
    """D-0007 camera noise r = var(e)·(1 − ρ₁) from raw residuals (time-ordered)."""
    e = np.asarray(resid, float)
    e = e[np.isfinite(e)]
    if len(e) < 10:
        return float("nan")
    rho = float(np.corrcoef(e[:-1], e[1:])[0, 1]) if np.std(e) > 0 else 0.0
    return max(float(np.var(e)) * (1 - np.clip(rho, 0.0, 0.95)), 1e-6)
