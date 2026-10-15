"""Small OpenCV-only plots for reports and the demo (no matplotlib in the product path)."""
from __future__ import annotations

import cv2
import numpy as np
import pandas as pd

WHITE, GREY, LIGHT = (255, 255, 255), (150, 150, 150), (235, 235, 235)
GAUGE, CAM, BAND, EVENT = (40, 40, 40), (200, 110, 20), (245, 215, 180), (210, 230, 255)


def _ticks(lo: float, hi: float, n: int = 5) -> np.ndarray:
    span = max(hi - lo, 1e-6)
    step = 10 ** np.floor(np.log10(span / n))
    for m in (1, 2, 2.5, 5, 10):
        if span / (step * m) <= n:
            step *= m
            break
    return np.arange(np.ceil(lo / step) * step, hi + 1e-9, step)


def timeseries_png(gauge: pd.Series, t: pd.DatetimeIndex, cam: np.ndarray, sigma: float, events: np.ndarray,
                   title: str, size=(1200, 420)) -> np.ndarray:
    """Gauge line, camera estimate ± σ band (per frame), event frames shaded."""
    W, H = size
    L, R, T, B = 70, 20, 40, 45
    img = np.full((H, W, 3), 255, np.uint8)
    t = pd.DatetimeIndex(t)
    t0, t1 = t.min() - pd.Timedelta("2h"), t.max() + pd.Timedelta("2h")
    g = gauge[(gauge.index >= t0) & (gauge.index <= t1)].dropna()
    vals = np.r_[g.values, cam[np.isfinite(cam)]]
    if np.isfinite(sigma):
        vals = np.r_[vals, cam[np.isfinite(cam)] + sigma, cam[np.isfinite(cam)] - sigma]
    lo, hi = np.nanmin(vals), np.nanmax(vals)
    pad = 0.08 * max(hi - lo, 0.2)
    lo, hi = lo - pad, hi + pad
    X = lambda tt: (L + (pd.DatetimeIndex(tt) - t0).total_seconds().values / (t1 - t0).total_seconds() * (W - L - R)).astype(int)
    Y = lambda v: (T + (hi - np.asarray(v, float)) / (hi - lo) * (H - T - B)).astype(int)
    xs = X(t)
    for x, e in zip(xs, events):
        if e:
            cv2.rectangle(img, (x - 2, T), (x + 2, H - B), EVENT, -1)
    for v in _ticks(lo, hi):
        y = int(Y([v])[0])
        cv2.line(img, (L, y), (W - R, y), LIGHT, 1)
        cv2.putText(img, f"{v:.2f}", (5, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, GREY, 1, cv2.LINE_AA)
    for d in pd.date_range(t0.ceil("D"), t1, freq="D"):
        x = int(X([d])[0])
        cv2.line(img, (x, T), (x, H - B), LIGHT, 1)
        cv2.putText(img, d.strftime("%m-%d"), (x - 18, H - B + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, GREY, 1, cv2.LINE_AA)
    ok = np.isfinite(cam)
    if np.isfinite(sigma):
        for x, c in zip(xs[ok], cam[ok]):
            cv2.line(img, (x, int(Y([c + sigma])[0])), (x, int(Y([c - sigma])[0])), BAND, 3)
    if len(g):
        pts = np.stack([X(g.index), Y(g.values)], 1).astype(np.int32)
        # break the gauge line at gaps > 2 h
        brk = np.flatnonzero(np.diff(g.index.asi8) > 2 * 3600e9) + 1
        for seg in np.split(pts, brk):
            cv2.polylines(img, [seg.reshape(-1, 1, 2)], False, GAUGE, 2, cv2.LINE_AA)
    for x, c in zip(xs[ok], cam[ok]):
        cv2.circle(img, (int(x), int(Y([c])[0])), 3, CAM, -1, cv2.LINE_AA)
    cv2.putText(img, title, (L, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(img, "gauge (line)  camera (dots, band = +/-1 sigma)  event frames shaded  [ft]", (W - 560, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, GREY, 1, cv2.LINE_AA)
    return img


def floodheight_colour(thr: np.ndarray, acc: np.ndarray, grid: tuple[int, int], lo: float, hi: float,
                       min_acc: float, size=(640, 360)) -> np.ndarray:
    """h* per block as a colour map (red = wets at low stage, blue = only at high stage); unreliable blocks grey."""
    th = thr.reshape(grid)
    norm = np.clip((th - lo) / max(hi - lo, 1e-6), 0, 1)
    col = cv2.applyColorMap((255 * (1 - norm)).astype(np.uint8), cv2.COLORMAP_JET)
    col[acc.reshape(grid) < min_acc] = (128, 128, 128)
    return cv2.resize(col, size, interpolation=cv2.INTER_NEAREST)


def legend_bar(lo: float, hi: float, height: int, width: int = 90) -> np.ndarray:
    bar = np.full((height, width, 3), 255, np.uint8)
    ramp = np.linspace(0, 255, height - 20).astype(np.uint8)[:, None]       # top = high stage (blue)
    c = cv2.applyColorMap(np.repeat(ramp, 18, 1), cv2.COLORMAP_JET)
    bar[10:height - 10, 6:24] = c
    for v in _ticks(lo, hi, 6):
        y = int(10 + (hi - v) / max(hi - lo, 1e-6) * (height - 20))
        cv2.putText(bar, f"{v:.1f} ft", (28, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1, cv2.LINE_AA)
    return bar
