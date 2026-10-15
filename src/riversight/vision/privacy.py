"""Privacy filter (non-negotiable 7): blur faces before any frame leaves the pipeline (dashboard, demo, LLM).

YuNet (OpenCV Zoo, face_detection_yunet_2023mar.onnx) through cv2.FaceDetectorYN — OpenCV 5's DNN engine.
Licence plates are not detected yet (no plate model in the pipeline); river cameras rarely see roads closely,
and demo frames are reviewed by eye before publishing.
"""
from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np

YUNET = Path(os.environ.get("RIVERSIGHT_MODELS", Path(__file__).resolve().parents[3] / "models" / "onnx")) / \
    "face_detection_yunet_2023mar.onnx"
_det = None


def blur_faces(img: np.ndarray, score: float = 0.6) -> tuple[np.ndarray, int]:
    """Return (copy with detected faces Gaussian-blurred, number of faces). Fails closed: raises if YuNet is missing."""
    global _det
    if not YUNET.exists():
        raise FileNotFoundError(f"YuNet model missing: {YUNET}")
    h, w = img.shape[:2]
    if _det is None:
        _det = cv2.FaceDetectorYN.create(str(YUNET), "", (w, h), score, 0.3, 5000)
    _det.setInputSize((w, h))
    _det.setScoreThreshold(score)
    _, faces = _det.detect(img)
    out = img.copy()
    n = 0 if faces is None else len(faces)
    for f in (faces if faces is not None else []):
        x, y, bw, bh = (int(round(v)) for v in f[:4])
        pad = int(0.25 * max(bw, bh))
        x0, y0, x1, y1 = max(x - pad, 0), max(y - pad, 0), min(x + bw + pad, w), min(y + bh + pad, h)
        if x1 > x0 and y1 > y0:
            k = max(3, (max(x1 - x0, y1 - y0) // 3) | 1)
            out[y0:y1, x0:x1] = cv2.GaussianBlur(out[y0:y1, x0:x1], (k, k), 0)
    return out, n
