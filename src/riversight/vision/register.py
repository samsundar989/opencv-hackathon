"""Frame-to-reference registration with OpenCV 5's `features` module.

Pipeline: ALIKED keypoints/descriptors → LightGlueMatcher → USAC_MAGSAC homography → score.
Falls back to ORB + BFMatcher (for the ablation and when ONNX models are missing).

Models (see docs/DATA_SOURCES.md §4): aliked-n16rot-top1k-640.onnx, aliked_lightglue.onnx.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


@dataclass
class Registration:
    H: Optional[np.ndarray]        # 3x3 homography mapping frame → reference, or None
    n_matches: int
    n_inliers: int
    reproj_err_px: float           # mean reprojection error on inliers
    score: float                   # 0..1 confidence (inlier ratio × inlier-count saturation)
    method: str

    @property
    def ok(self) -> bool:
        return self.H is not None and self.n_inliers >= 15 and self.score >= 0.25


class Registrar:
    """Holds one reference frame (per site) and registers new frames to it."""

    def __init__(self, aliked_onnx: Optional[Path] = None, lightglue_onnx: Optional[Path] = None,
                 use_aliked: bool = True, mask_rows_top: int = 0, mask_rows_bottom: int = 0):
        self.method = "orb"
        self._det = None
        self._lg = None
        self.mask_rows_top = mask_rows_top          # mask USGS overlay text bands so they don't become "features"
        self.mask_rows_bottom = mask_rows_bottom
        if use_aliked and aliked_onnx and lightglue_onnx and Path(aliked_onnx).exists() and Path(lightglue_onnx).exists() \
                and hasattr(cv2, "ALIKED") and hasattr(cv2, "LightGlueMatcher"):
            params = cv2.ALIKED_Params()
            self._det = cv2.ALIKED.create(str(aliked_onnx), params)
            self._lg = cv2.LightGlueMatcher.create(str(lightglue_onnx), 0.1)
            self.method = "aliked+lightglue"
        else:
            self._det = cv2.ORB.create(nfeatures=3000)
        self._ref_kp = None
        self._ref_desc = None
        self._ref_shape = None

    def _mask(self, img: np.ndarray) -> np.ndarray:
        m = np.full(img.shape[:2], 255, np.uint8)
        if self.mask_rows_top:
            m[: self.mask_rows_top, :] = 0
        if self.mask_rows_bottom:
            m[-self.mask_rows_bottom:, :] = 0
        return m

    def _detect(self, img: np.ndarray):
        gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if self.method == "aliked+lightglue":
            # ALIKED works on BGR/gray input; mask applied via detectAndCompute's mask param where supported
            kp, desc = self._det.detectAndCompute(img if img.ndim == 3 else cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), self._mask(img))
        else:
            kp, desc = self._det.detectAndCompute(gray, self._mask(img))
        return kp, desc

    def set_reference(self, ref_img: np.ndarray) -> int:
        self._ref_kp, self._ref_desc = self._detect(ref_img)
        self._ref_shape = ref_img.shape[:2]
        return 0 if self._ref_kp is None else len(self._ref_kp)

    def register(self, frame: np.ndarray) -> Registration:
        if self._ref_desc is None:
            raise RuntimeError("set_reference() first")
        kp, desc = self._detect(frame)
        if desc is None or len(kp) < 8 or self._ref_desc is None or len(self._ref_kp) < 8:
            return Registration(None, 0, 0, float("nan"), 0.0, self.method)
        if self.method == "aliked+lightglue":
            h, w = frame.shape[:2]
            self._lg.setPairInfo(w, h, self._ref_shape[1], self._ref_shape[0])
            matches = self._lg.match(desc, self._ref_desc, kp, self._ref_kp)
        else:
            bf = cv2.BFMatcher(cv2.NORM_HAMMING)
            knn = bf.knnMatch(desc, self._ref_desc, k=2)
            matches = [m for m, n in (p for p in knn if len(p) == 2) if m.distance < 0.75 * n.distance]
        if len(matches) < 8:
            return Registration(None, len(matches), 0, float("nan"), 0.0, self.method)
        src = np.float32([kp[m.queryIdx].pt for m in matches])
        dst = np.float32([self._ref_kp[m.trainIdx].pt for m in matches])
        H, inl = cv2.findHomography(src, dst, cv2.USAC_MAGSAC, 3.0, maxIters=5000, confidence=0.999)
        if H is None:
            return Registration(None, len(matches), 0, float("nan"), 0.0, self.method)
        inl = inl.ravel().astype(bool)
        n_inl = int(inl.sum())
        proj = cv2.perspectiveTransform(src[inl].reshape(-1, 1, 2), H).reshape(-1, 2) if n_inl else np.zeros((0, 2))
        err = float(np.mean(np.linalg.norm(proj - dst[inl], axis=1))) if n_inl else float("nan")
        ratio = n_inl / max(len(matches), 1)
        score = float(ratio * (1 - np.exp(-n_inl / 40.0)))
        return Registration(H, len(matches), n_inl, err, score, self.method)


def warp_to_reference(frame: np.ndarray, H: np.ndarray, ref_shape: tuple[int, int]) -> np.ndarray:
    """Warp a frame into reference coordinates (OpenCV 5's faster exact-bilinear warp path)."""
    h, w = ref_shape
    return cv2.warpPerspective(frame, H, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
