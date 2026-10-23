"""Synthetic camera faults for the agent evaluation (labelled `source: synthetic` in every episode).

Each fault is a deterministic function of (frame, seed), so an episode's frame key `synth:<fault>:<seed>:<base>`
reproduces the same pixels on any machine. Gauge faults (dropout, offset, drift) are not pixel faults; they are
applied to the gauge series the tools see (`tools.ToolContext.gauge_fault`).

  shift     random homography moving the corners 2–8 % of the width (a bumped/re-seated camera)
  fog       Gaussian blur + atmospheric haze toward a bright airlight
  droplets  rain drops on the lens: blurred discs over a lightly blurred frame
  occlusion a spider/leaf/blob covering 25–45 % of the lower frame
  ir        night IR frame: grayscale, contrast-stretched, dark, low saturation
"""
from __future__ import annotations

import cv2
import numpy as np

FAULTS = ("shift", "fog", "droplets", "occlusion", "ir")


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(1_000_003 * (seed + 1))


def shift(img: np.ndarray, seed: int, lo: float = 0.02, hi: float = 0.08) -> np.ndarray:
    r = _rng(seed)
    h, w = img.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    mag = r.uniform(lo, hi) * w
    d = r.normal(size=(4, 2))
    d = d / np.linalg.norm(d, axis=1, keepdims=True) * mag * r.uniform(0.5, 1.0, size=(4, 1))
    d += r.normal(size=(1, 2)) * mag * 0.5          # a common pan component
    H = cv2.getPerspectiveTransform(src, (src + d).astype(np.float32))
    return cv2.warpPerspective(img, H, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def fog(img: np.ndarray, seed: int) -> np.ndarray:
    r = _rng(seed)
    t = r.uniform(0.35, 0.55)                        # transmission
    air = r.uniform(200, 235)
    k = int(r.integers(5, 9)) * 2 + 1
    b = cv2.GaussianBlur(img, (k, k), 0).astype(np.float32)
    return np.clip(b * t + air * (1 - t), 0, 255).astype(np.uint8)


def droplets(img: np.ndarray, seed: int) -> np.ndarray:
    r = _rng(seed)
    h, w = img.shape[:2]
    out = cv2.GaussianBlur(img, (5, 5), 0)
    heavy = cv2.GaussianBlur(img, (41, 41), 0)
    mask = np.zeros((h, w), np.float32)
    for _ in range(int(r.integers(40, 90))):
        c = (int(r.integers(0, w)), int(r.integers(0, h)))
        rad = int(r.integers(int(0.01 * w), int(0.045 * w)))
        cv2.circle(mask, c, rad, 1.0, -1)
    mask = cv2.GaussianBlur(mask, (21, 21), 0)[..., None]
    return np.clip(out * (1 - mask) + (heavy * 0.9 + 25) * mask, 0, 255).astype(np.uint8)


def occlusion(img: np.ndarray, seed: int) -> np.ndarray:
    r = _rng(seed)
    h, w = img.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    cx, cy = int(r.uniform(0.25, 0.75) * w), int(r.uniform(0.55, 0.85) * h)
    ax, ay = int(r.uniform(0.25, 0.4) * w), int(r.uniform(0.25, 0.4) * h)
    cv2.ellipse(mask, (cx, cy), (ax, ay), float(r.uniform(0, 180)), 0, 360, 255, -1)
    m = cv2.GaussianBlur(mask, (61, 61), 0).astype(np.float32)[..., None] / 255.0
    blob = np.full_like(img, int(r.integers(15, 60)), dtype=np.uint8)
    return np.clip(img * (1 - m) + blob * m, 0, 255).astype(np.uint8)


def ir(img: np.ndarray, seed: int) -> np.ndarray:
    r = _rng(seed)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g = (g - g.mean()) * r.uniform(0.5, 0.8) + r.uniform(30, 42)
    g += r.normal(0, 4, g.shape).astype(np.float32)
    g = np.clip(g, 0, 255).astype(np.uint8)
    return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)


_FN = {"shift": shift, "fog": fog, "droplets": droplets, "occlusion": occlusion, "ir": ir}


def apply(img: np.ndarray, fault: str, seed: int) -> np.ndarray:
    if fault not in _FN:
        raise ValueError(f"unknown fault {fault!r}; known: {FAULTS}")
    return _FN[fault](img, seed)


def synth_key(fault: str, seed: int, base_key: str) -> str:
    return f"synth:{fault}:{seed}:{base_key}"
