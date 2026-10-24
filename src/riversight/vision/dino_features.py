"""DINOv2-S/14 patch tokens computed by OpenCV 5's DNN engine (model v2 candidate, W4 / D-0010 §2).

    registered 320×180 frame → cv2.dnn.blobFromImageWithParams (resize 392×224, RGB, ImageNet mean/std)
      → cv2.dnn Net (DINOv2-S/14, fixed-shape ONNX from scripts/v2_export_dino.py) → (16, 28, 384) tokens

The frame is the same registered, reference-geometry image the v1 block features use (`warp_small`), so a
DINO patch covers a fixed piece of the scene in every frame. Each patch is ~11.4×11.25 px of the 320×180
frame; `patch_of_block` maps v1's 4 px blocks onto it.

Tokens are stored after a fixed global PCA (`project`, fitted once on frames of sites that are not in the
kill test, no labels), which keeps 36k frames × 448 patches in ~1 GB.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np

from riversight.vision.scene_features import GRID, OUT_H, OUT_W

IN_H, IN_W = 224, 392
PGRID = (IN_H // 14, IN_W // 14)          # (16, 28) patches
DIM = 384
MEAN = (0.485, 0.456, 0.406)              # ImageNet, RGB
STD = (0.229, 0.224, 0.225)
ROOT = Path(__file__).resolve().parents[3]
MODEL = ROOT / "models" / "onnx" / "dinov2_small_224x392.onnx"
MODEL_SHA256 = "84c75599e4c99a3a81831e122a5670ebe8179a35aeee7d10b09bcf0fa88bdec7"


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_net(path: Path = MODEL, engine: str = "auto") -> "cv2.dnn.Net":
    """Read the ONNX graph with cv2.dnn. engine: 'auto' (OpenCV 5 default), 'new'/'opencv' or 'classic'.
    The ENGINE_* names differ between 5.0 (CLASSIC/NEW/AUTO) and 5.1 (OPENCV/ORT/AUTO): looked up by name,
    never by integer (CLAUDE.md rule 1)."""
    names = {"auto": ("ENGINE_AUTO",), "new": ("ENGINE_NEW", "ENGINE_OPENCV"),
             "opencv": ("ENGINE_OPENCV", "ENGINE_NEW"), "classic": ("ENGINE_CLASSIC",)}[engine]
    eng = next((getattr(cv2.dnn, n) for n in names if hasattr(cv2.dnn, n)), None)
    try:
        net = cv2.dnn.readNetFromONNX(str(path), eng) if eng is not None else cv2.dnn.readNetFromONNX(str(path))
    except TypeError:                     # builds without the engine argument
        net = cv2.dnn.readNetFromONNX(str(path))
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    return net


def blob(small_bgr: np.ndarray) -> np.ndarray:
    """320×180 BGR uint8 → (1, 3, 224, 392) float32 NCHW, RGB, (x/255 − mean)/std, done by OpenCV."""
    p = cv2.dnn.Image2BlobParams()
    p.scalefactor = tuple(1.0 / (255.0 * s) for s in STD)
    p.size = (IN_W, IN_H)
    p.mean = tuple(255.0 * m for m in MEAN)
    p.swapRB = True
    p.ddepth = cv2.CV_32F
    return cv2.dnn.blobFromImageWithParams(small_bgr, p)


def tokens(net, small_bgr: np.ndarray) -> np.ndarray:
    """(1+448, 384) float32: CLS token, then patch tokens in row-major 16×28 order."""
    net.setInput(blob(small_bgr))
    return np.asarray(net.forward()).reshape(-1, DIM)


def patch_of_block(grid: tuple[int, int] = GRID) -> np.ndarray:
    """(rows*cols,) index of the DINO patch whose centre region contains each v1 block centre."""
    r, c = grid
    bh, bw = OUT_H / r, OUT_W / c
    yc = (np.arange(r) + 0.5) * bh * IN_H / OUT_H
    xc = (np.arange(c) + 0.5) * bw * IN_W / OUT_W
    pr = np.clip((yc // 14).astype(int), 0, PGRID[0] - 1)
    pc = np.clip((xc // 14).astype(int), 0, PGRID[1] - 1)
    return (pr[:, None] * PGRID[1] + pc[None, :]).ravel()


def project(tok: np.ndarray, basis: dict) -> np.ndarray:
    """(…, 384) tokens → (…, k) with a fixed PCA basis {'mean': (384,), 'components': (k, 384)}."""
    return (tok - basis["mean"]) @ basis["components"].T
