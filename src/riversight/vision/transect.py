"""Transects: fixed polylines in reference-image coordinates along which we look for the waterline.

A transect is defined once per site (by a human in the site tool, or automatically from the
water-mask gradient) as a polyline from land (s=0) towards water (s=L). For each registered frame
we sample 1-D profiles along it with cv2.remap (bilinear) and detect the land→water transition.

This module is deliberately classical and fast: it is the fallback when the DNN is unavailable and
it is what runs on every frame on the Graviton worker (Sobel/Scharr/Laplacian/cvtColor are among the
operations COOL accelerates).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


@dataclass
class Transect:
    name: str
    points: np.ndarray  # (N,2) float32 polyline in reference image coords, land → water
    half_width: int = 3  # pixels sampled on each side of the line (averaged) to reduce noise

    @property
    def length(self) -> float:
        d = np.diff(self.points, axis=0)
        return float(np.sum(np.hypot(d[:, 0], d[:, 1])))

    def sample_points(self, step: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
        """Return (s, xy): arc-length positions and image coordinates along the polyline."""
        pts = self.points.astype(np.float64)
        seg = np.diff(pts, axis=0)
        seg_len = np.hypot(seg[:, 0], seg[:, 1])
        cum = np.concatenate([[0.0], np.cumsum(seg_len)])
        s = np.arange(0.0, cum[-1] + 1e-9, step)
        xy = np.empty((len(s), 2))
        xy[:, 0] = np.interp(s, cum, pts[:, 0])
        xy[:, 1] = np.interp(s, cum, pts[:, 1])
        return s, xy

    def normals(self, step: float = 1.0) -> np.ndarray:
        s, xy = self.sample_points(step)
        d = np.gradient(xy, axis=0)
        n = np.stack([-d[:, 1], d[:, 0]], axis=1)
        n /= np.maximum(np.hypot(n[:, 0], n[:, 1])[:, None], 1e-9)
        return n


def sample_profile(img: np.ndarray, t: Transect, step: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Sample an image along a transect, averaging across a band of width 2*half_width+1.

    Returns (s, values) where values has shape (len(s), C) for a C-channel image.
    Uses cv2.remap with bilinear interpolation.
    """
    s, xy = t.sample_points(step)
    n = t.normals(step)
    offsets = np.arange(-t.half_width, t.half_width + 1, dtype=np.float64)
    # build a (len(s), band) grid of sample coordinates
    gx = (xy[:, None, 0] + offsets[None, :] * n[:, None, 0]).astype(np.float32)
    gy = (xy[:, None, 1] + offsets[None, :] * n[:, None, 1]).astype(np.float32)
    samp = cv2.remap(img, gx, gy, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    if samp.ndim == 2:
        samp = samp[:, :, None]
    vals = samp.astype(np.float32).mean(axis=1)  # average across the band → (len(s), C)
    return s, vals


def profile_features(img_bgr: np.ndarray, t: Transect, step: float = 1.0) -> dict[str, np.ndarray]:
    """Classical 1-D features along a transect: gray, gradient magnitude, saturation, texture."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    gx = cv2.Scharr(gray, cv2.CV_32F, 1, 0)
    gy = cv2.Scharr(gray, cv2.CV_32F, 0, 1)
    gmag = cv2.magnitude(gx, gy)
    lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    tex = cv2.blur(np.abs(lap), (9, 9))  # local texture energy; water tends to be smoother/specular
    s, g = sample_profile(gray, t, step)
    _, m = sample_profile(gmag, t, step)
    _, sat = sample_profile(hsv[:, :, 1], t, step)
    _, hue = sample_profile(hsv[:, :, 0], t, step)
    _, tx = sample_profile(tex, t, step)
    return {"s": s, "gray": g[:, 0], "grad": m[:, 0], "sat": sat[:, 0], "hue": hue[:, 0], "texture": tx[:, 0]}


def detect_transition(features: dict[str, np.ndarray], prior_s: Optional[float] = None,
                      prior_sigma: float = 40.0, min_s: float = 5.0) -> tuple[float, float]:
    """Find the land→water transition along the transect.

    Score = normalized gradient magnitude × a texture-change term (land textured → water smooth),
    softly weighted towards a prior position (previous reading) if given. Returns (s*, confidence in
    [0,1]). Confidence is the peak's prominence relative to the profile.
    """
    s = features["s"]
    grad = features["grad"].copy()
    tex = features["texture"].copy()
    if len(s) < 8:
        return float("nan"), 0.0
    grad = cv2.GaussianBlur(grad.reshape(-1, 1), (1, 7), 0).ravel()
    grad = (grad - grad.min()) / (np.ptp(grad) + 1e-6)  # NumPy 2: ndarray.ptp was removed
    # texture-change: mean texture before minus after (land→water: positive)
    k = max(5, int(0.05 * len(s)))
    cs = np.concatenate([[0.0], np.cumsum(tex)])
    n = len(tex)
    i = np.arange(k, n - k)
    before = (cs[i] - cs[i - k]) / k   # mean texture over [i-k, i)
    after = (cs[i + k] - cs[i]) / k    # mean texture over [i, i+k)
    tchange = np.zeros_like(tex)
    tchange[i] = before - after
    tchange = np.clip(tchange / (np.abs(tchange).max() + 1e-6), 0, 1)
    score = grad * (0.5 + 0.5 * tchange)
    if prior_s is not None and np.isfinite(prior_s):
        score = score * np.exp(-0.5 * ((s - prior_s) / prior_sigma) ** 2) + 0.05 * score
    score[s < min_s] = 0
    i = int(np.argmax(score))
    peak = float(score[i])
    conf = float(np.clip((peak - np.median(score)) / (peak + 1e-6), 0, 1))
    return float(s[i]), conf
