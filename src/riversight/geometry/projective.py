"""The 'virtual staff' model: a 1-D projective map between stage h (ft) and waterline position u (px).

Physics: points on any straight 3-D line (a bank edge, pier, wall, staff) project to a straight
line in the image, and the map from metric position along the 3-D line to pixel position along
the image line is a 1-D homography (cross-ratio preserving):

    u(h) = (a*h + b) / (c*h + 1)

with three parameters. It is exact for a straight transect and a pinhole camera (after
undistortion), extrapolates sensibly beyond the observed stage range, and is invertible:

    h(u) = (b - u) / (c*u - a)

Fitting: the model is linear in (a, b, c) after multiplying out:  a*h + b - c*(u*h) = u.
We fit robustly with IRLS (Huber) on top of a RANSAC-style minimal-sample search so that
outliers (bad waterline detections, gauge glitches) do not bend the curve.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class ProjectiveModel:
    a: float
    b: float
    c: float
    rmse_px: float = float("nan")
    n_inliers: int = 0
    n_total: int = 0
    h_min: float = float("nan")  # observed stage range used for the fit (for extrapolation flags)
    h_max: float = float("nan")

    def u(self, h):
        h = np.asarray(h, dtype=float)
        return (self.a * h + self.b) / (self.c * h + 1.0)

    def h(self, u):
        u = np.asarray(u, dtype=float)
        den = self.c * u - self.a
        with np.errstate(divide="ignore", invalid="ignore"):
            return (self.b - u) / den

    def du_dh(self, h):
        """Pixels per foot at stage h (sensitivity). Sign is constant if the model is monotone."""
        h = np.asarray(h, dtype=float)
        return (self.a - self.b * self.c) / (self.c * h + 1.0) ** 2

    def sigma_h(self, h, sigma_u_px: float):
        """Propagate a waterline pixel uncertainty into feet at stage h."""
        s = np.abs(self.du_dh(h))
        with np.errstate(divide="ignore"):
            return np.where(s > 1e-9, sigma_u_px / s, np.inf)

    def is_monotone_over(self, h_lo: float, h_hi: float) -> bool:
        """No pole (c*h+1 = 0) inside [h_lo, h_hi] and non-zero slope."""
        if abs(self.a - self.b * self.c) < 1e-12:
            return False
        if abs(self.c) < 1e-12:
            return True
        pole = -1.0 / self.c
        return not (h_lo <= pole <= h_hi)

    def as_dict(self) -> dict:
        return {"a": self.a, "b": self.b, "c": self.c, "rmse_px": self.rmse_px, "n_inliers": self.n_inliers,
                "n_total": self.n_total, "h_min": self.h_min, "h_max": self.h_max}


def _solve_ls(h: np.ndarray, u: np.ndarray, w: Optional[np.ndarray] = None) -> Optional[np.ndarray]:
    A = np.stack([h, np.ones_like(h), -u * h], axis=1)
    y = u
    if w is not None:
        sw = np.sqrt(w)[:, None]
        A, y = A * sw, y * sw[:, 0]
    try:
        sol, *_ = np.linalg.lstsq(A, y, rcond=None)
    except np.linalg.LinAlgError:
        return None
    return sol


def fit_linear(h, u) -> ProjectiveModel:
    """Plain least squares (no robustness). Useful as a starting point and as an ablation."""
    h, u = np.asarray(h, float), np.asarray(u, float)
    sol = _solve_ls(h, u)
    if sol is None:
        raise ValueError("degenerate fit")
    a, b, c = sol
    m = ProjectiveModel(a, b, c)
    r = m.u(h) - u
    return ProjectiveModel(a, b, c, float(np.sqrt(np.mean(r ** 2))), len(h), len(h), float(h.min()), float(h.max()))


def _pole_ok(c: float, a: float, b: float, lo: float, hi: float) -> bool:
    """Physically admissible: non-zero slope and no pole (c*h + 1 = 0) inside [lo, hi]."""
    if abs(a - b * c) < 1e-9:
        return False
    if abs(c) < 1e-12:
        return True
    return not (lo <= -1.0 / c <= hi)


def fit_robust(h, u, *, inlier_px: float = 6.0, n_iter: int = 300, huber_px: float = 3.0,
               seed: int = 0, min_points: int = 3, pole_margin: float = 1.0,
               min_range_for_curvature: float = 1.0) -> ProjectiveModel:
    """RANSAC (3-point minimal samples) + Huber IRLS refinement.

    h: stage values (ft), u: waterline positions (px along a transect). Returns the model with the
    most inliers (|residual| <= inlier_px), refined on the inliers.
    """
    h, u = np.asarray(h, float), np.asarray(u, float)
    ok = np.isfinite(h) & np.isfinite(u)
    h, u = h[ok], u[ok]
    n = len(h)
    if n < min_points:
        raise ValueError(f"need at least {min_points} points, got {n}")
    span = float(h.max() - h.min())
    lo, hi = float(h.min()) - pole_margin * max(span, 1.0), float(h.max()) + pole_margin * max(span, 1.0)
    # Over a short stage range the curvature term is not identifiable: fit the c=0 (affine) member.
    if span < min_range_for_curvature:
        return _fit_affine_robust(h, u, inlier_px=inlier_px, huber_px=huber_px, n_iter=n_iter, seed=seed)
    rng = np.random.default_rng(seed)
    best_inl = None
    best_cnt = -1
    # Always try the global LS solution as a candidate too.
    cands = []
    g = _solve_ls(h, u)
    if g is not None:
        cands.append(g)
    for _ in range(n_iter if n > 3 else 1):
        idx = rng.choice(n, size=3, replace=False)
        sol = _solve_ls(h[idx], u[idx])
        if sol is None or not np.all(np.isfinite(sol)):
            continue
        cands.append(sol)
    for sol in cands:
        a, b, c = sol
        if not _pole_ok(c, a, b, lo, hi):
            continue
        den = c * h + 1.0
        if np.any(np.abs(den) < 1e-6):
            continue
        pred = (a * h + b) / den
        inl = np.abs(pred - u) <= inlier_px
        cnt = int(inl.sum())
        if cnt > best_cnt:
            best_cnt, best_inl = cnt, inl
    if best_inl is None or best_cnt < min_points:
        return _fit_affine_robust(h, u, inlier_px=inlier_px, huber_px=huber_px, n_iter=n_iter, seed=seed)
    # Huber IRLS on inliers (then re-select inliers once)
    h_in, ui = h[best_inl], u[best_inl]
    sol = _solve_ls(h_in, ui)
    if sol is None or not _pole_ok(sol[2], sol[0], sol[1], lo, hi):
        sol = max((c_ for c_ in cands if _pole_ok(c_[2], c_[0], c_[1], lo, hi)),
                  key=lambda c_: int((np.abs((c_[0] * h + c_[1]) / (c_[2] * h + 1.0) - u) <= inlier_px).sum()))
    for _ in range(10):
        a, b, c = sol
        r = (a * h_in + b) / (c * h_in + 1.0) - ui
        w = np.where(np.abs(r) <= huber_px, 1.0, huber_px / np.maximum(np.abs(r), 1e-9))
        new = _solve_ls(h_in, ui, w)
        if new is None or np.allclose(new, sol, atol=1e-9) or not _pole_ok(new[2], new[0], new[1], lo, hi):
            break
        sol = new
    a, b, c = sol
    m = ProjectiveModel(a, b, c)
    r_all = m.u(h) - u
    inl = np.abs(r_all) <= inlier_px
    rmse = float(np.sqrt(np.mean(r_all[inl] ** 2))) if inl.any() else float("nan")
    return ProjectiveModel(a, b, c, rmse, int(inl.sum()), int(n), float(h[inl].min()), float(h[inl].max()))


def _fit_affine_robust(h, u, *, inlier_px: float, huber_px: float, n_iter: int, seed: int) -> ProjectiveModel:
    """c = 0 member of the family (u = a*h + b): 2-point RANSAC + Huber IRLS."""
    rng = np.random.default_rng(seed)
    n = len(h)
    best, best_cnt = None, -1
    for _ in range(n_iter):
        i, j = rng.choice(n, size=2, replace=False)
        if abs(h[i] - h[j]) < 1e-6:
            continue
        a = (u[i] - u[j]) / (h[i] - h[j])
        b = u[i] - a * h[i]
        cnt = int((np.abs(a * h + b - u) <= inlier_px).sum())
        if cnt > best_cnt and abs(a) > 1e-9:
            best, best_cnt = (a, b), cnt
    if best is None:
        raise ValueError("degenerate stage range")
    a, b = best
    for _ in range(10):
        r = a * h + b - u
        w = np.where(np.abs(r) <= max(inlier_px, huber_px), 1.0, huber_px / np.maximum(np.abs(r), 1e-9))
        A = np.stack([h, np.ones_like(h)], 1) * np.sqrt(w)[:, None]
        sol, *_ = np.linalg.lstsq(A, u * np.sqrt(w), rcond=None)
        if np.allclose(sol, (a, b), atol=1e-9):
            break
        a, b = sol
    if abs(a) < 1e-9:
        raise ValueError("zero slope")
    r = a * h + b - u
    inl = np.abs(r) <= inlier_px
    rmse = float(np.sqrt(np.mean(r[inl] ** 2))) if inl.any() else float("nan")
    return ProjectiveModel(float(a), float(b), 0.0, rmse, int(inl.sum()), int(n),
                           float(h[inl].min()) if inl.any() else float(h.min()),
                           float(h[inl].max()) if inl.any() else float(h.max()))


def fit_isotonic_lookup(h, u, n_bins: int = 64):
    """Non-physics baseline: monotone lookup table u(h) via pool-adjacent-violators on binned medians.

    Returns (h_knots, u_knots) usable with np.interp in either direction (after sorting by u).
    """
    h, u = np.asarray(h, float), np.asarray(u, float)
    ok = np.isfinite(h) & np.isfinite(u)
    h, u = h[ok], u[ok]
    order = np.argsort(h)
    h, u = h[order], u[order]
    # bin by stage quantiles
    edges = np.quantile(h, np.linspace(0, 1, n_bins + 1))
    hk, uk = [], []
    for i in range(n_bins):
        m = (h >= edges[i]) & (h <= edges[i + 1]) if i == n_bins - 1 else (h >= edges[i]) & (h < edges[i + 1])
        if m.sum() >= 3:
            hk.append(float(np.median(h[m])))
            uk.append(float(np.median(u[m])))
    hk, uk = np.array(hk), np.array(uk)
    if len(hk) < 2:
        raise ValueError("not enough bins")
    # decide direction from overall correlation, then PAV
    sign = 1.0 if np.corrcoef(hk, uk)[0, 1] >= 0 else -1.0
    y = sign * uk
    # pool adjacent violators (increasing)
    blocks = [[y[i], 1, hk[i], hk[i]] for i in range(len(y))]  # mean, count, hmin, hmax
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] > blocks[i + 1][0]:
            m0, c0, _, _ = blocks[i]
            m1, c1, _, _ = blocks[i + 1]
            merged = [(m0 * c0 + m1 * c1) / (c0 + c1), c0 + c1, blocks[i][2], blocks[i + 1][3]]
            blocks[i:i + 2] = [merged]
            i = max(i - 1, 0)
        else:
            i += 1
    hk2 = np.array([(b[2] + b[3]) / 2 for b in blocks])
    uk2 = sign * np.array([b[0] for b in blocks])
    return hk2, uk2
