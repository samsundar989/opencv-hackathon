"""Flood-height map: the stage h* at which each image block turns from dry to wet (D-0006).

For every block, try thresholds q over the stage quantiles of the calibration frames. At each q, split the
frames into wet (stage ≥ q) and dry, and fit a Fisher-style linear discriminant on the block's features:
w = (m_wet − m_dry) / (v_wet + v_dry), decision s = w·(x − mid) > 0. Keep the q with the best balanced
accuracy; that accuracy is the block's **reliability** and q is its **inundation threshold h***.

Uses:
  * ROI for the scene regressor (blocks with reliability ≥ 0.85 respond physically to water);
  * a stage estimate on its own (`vote`): every reliable block says wet/dry, and the stage is the value
    that agrees with the most (reliability-weighted) votes;
  * the demo visual: a colour map of h* over the reference frame, and "draw the flood into the image"
    (wet area at stage ŝ = blocks with h* ≤ ŝ).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class FloodHeightMap:
    acc: np.ndarray    # (B,) balanced accuracy of the best split (reliability), −1 if never fitted
    thr: np.ndarray    # (B,) inundation threshold h*, ft
    w: np.ndarray      # (B, d) discriminant weights
    mid: np.ndarray    # (B, d) discriminant midpoint

    def reliable(self, min_acc: float = 0.85) -> np.ndarray:
        return self.acc >= min_acc

    def wet(self, X: np.ndarray, sel: np.ndarray | None = None) -> np.ndarray:
        """(n, B, d) features → (n, B) bool wet votes (restricted to `sel` blocks if given)."""
        w, mid = (self.w, self.mid) if sel is None else (self.w[sel], self.mid[sel])
        Xs = X if sel is None else X[:, sel]
        return np.einsum("nbd,bd->nb", Xs - mid, w) > 0

    def wet_at(self, stage: float, min_acc: float = 0.85) -> np.ndarray:
        """(B,) blocks predicted under water at `stage` (reliable blocks with h* ≤ stage)."""
        return self.reliable(min_acc) & (self.thr <= stage)


def fit_thr(X: np.ndarray, h: np.ndarray, nq: int = 24, minside: int = 8) -> FloodHeightMap:
    """X (n, B, d) block features, h (n,) stage → per-block best wet/dry split over stage quantiles."""
    n, B, d = X.shape
    X = X.astype(np.float32, copy=False)
    qs = np.unique(np.quantile(h, np.linspace(0.04, 0.96, nq)))
    best = np.full(B, -1.0)
    bthr = np.zeros(B)
    bw = np.zeros((B, d), np.float32)
    bmid = np.zeros((B, d), np.float32)
    for q in qs:
        wet = h >= q
        n1 = int(wet.sum())
        if n1 < minside or n - n1 < minside:
            continue
        m1, m0 = X[wet].mean(0), X[~wet].mean(0)
        v1, v0 = X[wet].var(0) + 1e-3, X[~wet].var(0) + 1e-3
        w = (m1 - m0) / (v1 + v0)
        mid = (m1 + m0) / 2
        pred = np.einsum("nbd,bd->nb", X - mid, w) > 0
        bacc = 0.5 * (pred[wet].mean(0) + (~pred[~wet]).mean(0))
        upd = bacc > best
        best[upd], bthr[upd], bw[upd], bmid[upd] = bacc[upd], q, w[upd], mid[upd]
    return FloodHeightMap(acc=best, thr=bthr, w=bw, mid=bmid)


def vote(M: FloodHeightMap, X: np.ndarray, grid: np.ndarray, min_acc: float = 0.85,
         min_blocks: int = 5) -> tuple[np.ndarray, int]:
    """Stage per frame = grid value(s) agreeing with the most reliability-weighted wet/dry votes.

    A block with threshold h* agrees with stage g when (wet and h* ≤ g) or (dry and h* > g). Returns
    (predictions, number of voting blocks); NaN predictions when fewer than `min_blocks` are reliable."""
    sel = M.reliable(min_acc)
    if sel.sum() < min_blocks:
        return np.full(len(X), np.nan), int(sel.sum())
    wt = M.acc[sel] - 0.5
    wet = M.wet(X, sel)
    G = len(grid)
    idx = np.clip(np.searchsorted(grid, M.thr[sel] - 1e-9), 0, G)   # first grid index with grid ≥ h*
    out = np.empty(len(X))
    for i in range(len(X)):
        hw = np.bincount(idx[wet[i]], wt[wet[i]], minlength=G + 1)[:G]
        hd = np.bincount(idx[~wet[i]], wt[~wet[i]], minlength=G + 1)
        score = np.cumsum(hw) + (hd.sum() - np.cumsum(hd)[:G])
        j = np.flatnonzero(score >= score.max() - 1e-9)
        out[i] = grid[j].mean()
    return out, int(sel.sum())


def stage_grid(h: np.ndarray, step: float = 0.01) -> np.ndarray:
    return np.arange(np.min(h), np.max(h) + step / 2, step)
