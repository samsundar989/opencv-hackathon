"""Per-block appearance features of a registered frame (scene model input, D-0006).

A frame is warped into its site's reference geometry, downsized to 320×180 and cut into square blocks
(4 px → 80×45 = 3,600 blocks). Each block carries five numbers:

  0  L − frame median L     (Lab lightness, illumination-normalised per frame)
  1  a                      (Lab green–red)
  2  b                      (Lab blue–yellow)
  3  Sobel gradient magnitude of L (texture: ripples, whitewater, exposed rock)
  4  L standard deviation inside the block

Features are stored at block size 4. Block size 8 is derived exactly from them (`pool_blocks`), so the
block-size knob in SLICE_01B step 3 never needs a second pass over the images.
"""
from __future__ import annotations

import cv2
import numpy as np

OUT_W, OUT_H = 320, 180
BS = 4
GRID = (OUT_H // BS, OUT_W // BS)   # (rows, cols) = (45, 80)
N_FEAT = 5


def warp_small(frame: np.ndarray, H: np.ndarray | None, ref_shape: tuple[int, int]) -> np.ndarray:
    """Warp a frame into reference geometry (full reference resolution), then area-downsize to 320×180.

    BORDER_REPLICATE keeps the few pixels that fall outside the frame from becoming a black wedge whose
    size would vary with the homography (that would be a registration feature, not a water feature)."""
    h, w = ref_shape
    if H is not None:
        frame = cv2.warpPerspective(frame, H, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    elif frame.shape[:2] != (h, w):
        frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
    return cv2.resize(frame, (OUT_W, OUT_H), interpolation=cv2.INTER_AREA)


def block_features(small: np.ndarray, bs: int = BS) -> np.ndarray:
    """320×180 BGR uint8 → (n_blocks, 5) float32 in row-major block order."""
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = lab[..., 0]
    gx = cv2.Sobel(L, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(L, cv2.CV_32F, 0, 1)
    gm = cv2.magnitude(gx, gy)
    ch = np.stack([L - np.median(L), lab[..., 1], lab[..., 2], gm], -1)
    h, w = ch.shape[:2]
    b = ch[: h - h % bs, : w - w % bs].reshape(h // bs, bs, w // bs, bs, 4)
    mean = b.mean((1, 3))
    sd = b[..., 0].std((1, 3))[..., None]
    return np.concatenate([mean, sd], -1).reshape(-1, N_FEAT).astype(np.float32)


def pool_blocks(X: np.ndarray, grid: tuple[int, int] = GRID, factor: int = 2) -> np.ndarray:
    """(n, rows*cols, 5) features at block size s → (n, rows/f * cols/f, 5) at block size s*f, exactly.

    Means average; the L std is pooled as sqrt(E[sd² + m²] − M²) over the sub-blocks (the L mean is the
    median-subtracted one, which shifts every sub-block equally and so leaves the variance unchanged).
    Rows/cols that do not divide by `factor` are dropped (45 rows → 22 at factor 2)."""
    n = X.shape[0]
    r, c = grid
    r2, c2 = r // factor, c // factor
    G = X.reshape(n, r, c, N_FEAT)[:, : r2 * factor, : c2 * factor].reshape(n, r2, factor, c2, factor, N_FEAT)
    G = G.astype(np.float64)
    mean = G[..., :4].mean((2, 4))
    m, sd = G[..., 0], G[..., 4]
    var = (sd ** 2 + m ** 2).mean((2, 4)) - mean[..., 0] ** 2
    out = np.concatenate([mean, np.sqrt(np.clip(var, 0, None))[..., None]], -1)
    return out.reshape(n, r2 * c2, N_FEAT).astype(np.float32)


def grid_for(n_blocks: int) -> tuple[int, int]:
    """Block grid shape for a feature matrix produced by block_features / pool_blocks."""
    for g in (GRID, (GRID[0] // 2, GRID[1] // 2)):
        if g[0] * g[1] == n_blocks:
            return g
    raise ValueError(f"unknown block grid for {n_blocks} blocks")
