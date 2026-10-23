"""Image-quality metrics for the live cycle (INTERFACES §2 `quality`), all on the 720-px frame below the
USGS overlay band.

  lap_var     variance of the Laplacian of gray (focus / rain on the lens / fog lower it)
  mean_v      mean HSV value (exposure)
  glare_frac  fraction of pixels with V ≥ 250 (sun glare, floodlights)
  fog_score   mean dark channel (He et al.): per-pixel min over BGR, eroded 15×15, /255. Haze lifts it.
  night       the SLICE_01 pixel test (low saturation = IR, or dark)

LOW_QUALITY fires when lap_var < calibration p5 or fog_score > calibration p95 (per site, meta.json).
"""
from __future__ import annotations

import cv2
import numpy as np

MASK_TOP = 56
NIGHT_SAT, NIGHT_VAL = 12.0, 45.0   # killtest.Cfg
_KERNEL = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))


def image_quality(img: np.ndarray, mask_top: int = MASK_TOP) -> dict:
    body = img[mask_top:]
    small = cv2.resize(body, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    dark = cv2.erode(small.min(axis=2), _KERNEL)
    return {
        "lap_var": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2),
        "mean_v": round(float(hsv[..., 2].mean()), 2),
        "glare_frac": round(float((hsv[..., 2] >= 250).mean()), 4),
        "fog_score": round(float(dark.mean()) / 255.0, 4),
        "night_img": bool(hsv[..., 1].mean() < NIGHT_SAT or hsv[..., 2].mean() < NIGHT_VAL),
    }
