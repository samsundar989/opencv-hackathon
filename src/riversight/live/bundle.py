"""Per-site model bundle (INTERFACES §1): fit, save, load, predict one frame, step the Kalman filter.

The D-0007 scene model is a linear-kernel ridge on standardised ROI block features. A linear kernel
ridge has an exact primal form, so the bundle stores one weight vector instead of the training matrix:

    ŷ = ((x − μ) / s) · w + ȳ,   w = Aᵀα / D,   α = (K + cI)⁻¹ (y − ȳ),   K = AAᵀ / D

which is the same number `scripts/scene_tune._eig_ridge` produces (tests/w1/test_bundle.py checks it).

Files in models/sites/<cam>/:
  reference.jpg            main registration reference (720 px)
  reference_<yyyymmdd>.jpg view-change segment references (history/segments.csv); link H in meta.json
  scene_model.npz          ROI, μ, s, w, ȳ, flood-height map (thr, acc, w, mid), Kalman q and r
  hstar.json               h* per block (null = unreliable) for the dashboard's client-side stage slider
  meta.json                INTERFACES §1 fields (+ quality p-levels, extra references)
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from riversight.calib.flood_height_map import FloodHeightMap, fit_thr
from riversight.vision.scene_features import GRID, OUT_H, OUT_W, block_features

PAD = 96   # px of replicated border before warping (see warp_small_safe)


def warp_small_safe(frame: np.ndarray, H: np.ndarray | None, ref_shape: tuple[int, int]) -> np.ndarray:
    """Same output as `scene_features.warp_small`, without `warpPerspective(..., BORDER_REPLICATE)`.

    KleidiCV on arm64 has a warpPerspective + BORDER_REPLICATE bug (opencv #29816). Padding the source with
    `copyMakeBorder(BORDER_REPLICATE)` and warping with BORDER_CONSTANT gives the same pixels for every
    destination pixel that lands within PAD px of the frame (all of them for a plausible fixed-camera H)."""
    h, w = ref_shape
    if H is not None:
        src = cv2.copyMakeBorder(frame, PAD, PAD, PAD, PAD, cv2.BORDER_REPLICATE)
        shift = np.array([[1, 0, -PAD], [0, 1, -PAD], [0, 0, 1]], float)     # padded → frame coordinates
        frame = cv2.warpPerspective(src, np.asarray(H, float).reshape(3, 3) @ shift, (w, h),
                                    flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    elif frame.shape[:2] != (h, w):
        frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
    return cv2.resize(frame, (OUT_W, OUT_H), interpolation=cv2.INTER_AREA)


def frame_features(frame: np.ndarray, H: np.ndarray | None, ref_shape: tuple[int, int]) -> np.ndarray:
    """Registered frame → (3600, 5) block features, as stored in the training caches (float16-rounded)."""
    return block_features(warp_small_safe(frame, H, ref_shape)).astype(np.float16).astype(np.float32)


# ---- fitting ----------------------------------------------------------------------------------------

def fit_ridge_primal(A_raw: np.ndarray, y: np.ndarray, lam: float):
    """(μ, s, w, ȳ, loo residuals) of the linear-kernel ridge used by scene_tune._eig_ridge."""
    mu = A_raw.mean(0)
    sd = A_raw.std(0) + 1e-3
    A = (A_raw - mu) / sd
    D = A.shape[1]
    K = (A @ A.T).astype(np.float64) / D
    e, V = np.linalg.eigh(K)
    ym = float(y.mean())
    inv = 1.0 / (e + lam * 0.05)
    alpha = V @ (inv * (V.T @ (y - ym)))
    loo = alpha / ((V ** 2) @ inv)
    w = (A.T.astype(np.float64) @ alpha) / D
    return mu.astype(np.float32), sd.astype(np.float32), w.astype(np.float64), ym, loo


def kalman_q(t_gauge, h_gauge) -> float:
    """Process variance per hour = variance of the gauge's hourly increments (D-0007)."""
    import pandas as pd
    s = pd.Series(np.asarray(h_gauge, float), index=pd.DatetimeIndex(t_gauge)).dropna()
    dh = np.diff(s.resample("1h").median().dropna().values)
    return max(float(np.var(dh)) if len(dh) > 2 else 1e-3, 1e-6)


def fit_scene_model(X: np.ndarray, h: np.ndarray, cfg: dict, q: float) -> dict:
    """X (n, 3600, 5) time-ordered training features, h (n,) gauge stage → scene_model arrays."""
    X = X.astype(np.float32, copy=False)
    M = fit_thr(X, h)
    roi = M.acc >= cfg["thr"]
    if roi.sum() < cfg["min_roi"]:
        roi = np.ones_like(roi)
    mu, sd, w, ym, loo = fit_ridge_primal(X[:, roi].reshape(len(X), -1), np.asarray(h, float), cfg["lam"])
    rho = np.corrcoef(loo[:-1], loo[1:])[0, 1]
    r = max(float(np.var(loo)) * (1 - np.clip(rho, 0, 0.95)), 1e-6)
    return {"roi": roi, "mu": mu, "sd": sd, "w": w, "ym": np.float64(ym), "q": np.float64(q), "r": np.float64(r),
            "fhm_acc": M.acc, "fhm_thr": M.thr, "fhm_w": M.w, "fhm_mid": M.mid, "min_acc": np.float64(cfg["thr"])}


def hstar_json(arr: dict, lo: float, hi: float) -> dict:
    reliable = arr["fhm_acc"] >= float(arr["min_acc"])
    thr = [round(float(v), 3) if ok else None for v, ok in zip(arr["fhm_thr"], reliable)]
    return {"grid": list(GRID), "block_px": 4, "small_wh": [OUT_W, OUT_H], "lo": round(lo, 3), "hi": round(hi, 3),
            "thr": thr, "note": "h* in ft per 4-px block of the 320x180 reference; null = unreliable block"}


def sha_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ---- loading / inference ----------------------------------------------------------------------------

@dataclass
class KalmanState:
    x: float = float("nan")
    P: float = float("inf")
    t: float | None = None      # unix seconds of the last update

    def to_json(self) -> dict:
        return {"x": None if not np.isfinite(self.x) else self.x,
                "P": None if not np.isfinite(self.P) else self.P, "t": self.t}

    @classmethod
    def from_json(cls, d: dict | None) -> "KalmanState":
        if not d:
            return cls()
        return cls(float("nan") if d.get("x") is None else d["x"], float("inf") if d.get("P") is None else d["P"], d.get("t"))


class SiteModel:
    def __init__(self, d: Path):
        self.dir = Path(d)
        self.meta = json.loads((self.dir / "meta.json").read_text(encoding="utf-8"))
        z = np.load(self.dir / "scene_model.npz")
        self.a = {k: z[k] for k in z.files}
        self.roi = self.a["roi"].astype(bool)
        self.fhm = FloodHeightMap(self.a["fhm_acc"], self.a["fhm_thr"], self.a["fhm_w"], self.a["fhm_mid"])
        self._ref = None

    @property
    def cam_id(self) -> str:
        return self.meta["cam_id"]

    def reference(self) -> np.ndarray:
        if self._ref is None:
            self._ref = cv2.imread(str(self.dir / "reference.jpg"))
        return self._ref

    def predict_raw(self, F: np.ndarray) -> np.ndarray:
        """(3600, 5) or (n, 3600, 5) block features → raw (unsmoothed) stage, ft."""
        F = F[None] if F.ndim == 2 else F
        A = (F[:, self.roi].reshape(len(F), -1).astype(np.float32) - self.a["mu"]) / self.a["sd"]
        return A.astype(np.float64) @ self.a["w"] + float(self.a["ym"])

    def kalman_step(self, s: KalmanState, t_unix: float, z: float) -> tuple[KalmanState, float, float]:
        """One step of `scene_regressor.kalman_1d` (random walk, irregular times). Returns (state, x, σ)."""
        x, P = s.x, s.P
        if s.t is not None and np.isfinite(x):
            P = P + float(self.a["q"]) * max((t_unix - s.t) / 3600.0, 0.0)
        r = float(self.a["r"])
        if np.isfinite(z):
            if not np.isfinite(x):
                x, P = z, r
            else:
                K = P / (P + r)
                x, P = x + K * (z - x), (1 - K) * P
        return KalmanState(x, P, t_unix), x, (np.sqrt(P) if np.isfinite(P) else float("nan"))

    def wet_mask(self, stage: float) -> np.ndarray:
        """(rows, cols) bool: reliable blocks with h* ≤ stage (unconnected; see wet_connected for display)."""
        return self.fhm.wet_at(stage, float(self.a["min_acc"])).reshape(GRID)

    def seed(self) -> np.ndarray:
        if getattr(self, "_seed", None) is None:
            self._seed = inundation_seed(self.a["fhm_thr"], self.a["fhm_acc"], float(self.a["min_acc"]))
        return self._seed

    def wet_connected(self, stage: float) -> np.ndarray:
        """(rows, cols) bool: what is under water at `stage`, physically: only blocks hydraulically connected
        to the always-wet river (D-0011 W1-1). Display only; the stage estimate never uses it."""
        return connected_inundation(self.a["fhm_thr"], self.a["fhm_acc"], float(self.a["min_acc"]), stage, self.seed())


# ---- connected inundation (display) -----------------------------------------------------------------

def _components(mask: np.ndarray) -> tuple[int, np.ndarray, np.ndarray]:
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=4)
    return n, lab, stats


def inundation_seed(thr: np.ndarray, acc: np.ndarray, min_acc: float, grid: tuple[int, int] = GRID) -> np.ndarray:
    """(rows, cols) bool seed for the flood-fill: the lowest blocks of the river corridor.

    The corridor is the 4-connected component of reliable blocks (all of them, i.e. wet at the calibration
    maximum) with the largest area × (centroid height in the frame)²: water lies low in a river camera's view,
    while reliable specks on foliage, sky or glare lie high and are small. The seed is the corridor's blocks
    with h* in its lowest decile, so the fill starts at the water's edge at its typical level and grows
    with stage only through connected blocks."""
    R = (acc >= min_acc).reshape(grid)
    h = thr.reshape(grid)
    n, lab, stats = _components(R)
    if n <= 1:
        return np.zeros(grid, bool)
    cy = np.array([np.mean(np.nonzero(lab == k)[0]) for k in range(1, n)]) / grid[0]
    corridor = lab == (int(np.argmax(stats[1:, cv2.CC_STAT_AREA] * cy ** 2)) + 1)
    return corridor & (h <= np.quantile(h[corridor], 0.10) + 1e-6)


def connected_inundation(thr: np.ndarray, acc: np.ndarray, min_acc: float, stage: float, seed: np.ndarray,
                         grid: tuple[int, int] = GRID) -> np.ndarray:
    """Blocks with h* ≤ stage that are 4-connected (through other such blocks) to the seed."""
    cand = ((acc >= min_acc) & (thr <= stage)).reshape(grid)
    if not seed.any():
        return np.zeros(grid, bool)
    n, lab, _ = _components(cand)
    hit = np.unique(lab[seed & cand])
    return np.isin(lab, hit[hit > 0])
