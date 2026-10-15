"""SLICE_01B scene model: features, flood-height map, regressor, smoothing and protocol v2 (synthetic data)."""
import numpy as np
import pandas as pd

from riversight.calib.flood_height_map import fit_thr, stage_grid, vote
from riversight.calib.scene_regressor import SceneRegressor, causal_median, kalman_1d, kernel_ridge
from riversight.eval import protocol_v2 as pv
from riversight.vision.scene_features import GRID, block_features, grid_for, pool_blocks, warp_small


def _scene(n=400, h_star=5.0, n_band=60, seed=0):
    """Stage h ~ U(3, 7); `n_band` blocks darken (L −30) and smooth out once h ≥ h_star; others are noise."""
    rng = np.random.default_rng(seed)
    h = rng.uniform(3, 7, n)
    B = 200
    X = rng.normal(0, 3, (n, B, 5)).astype(np.float32)
    wet = h >= h_star
    X[wet, :n_band, 0] -= 30
    X[wet, :n_band, 3] -= 10
    return X, h, n_band


def test_block_features_shape_and_illumination_normalisation():
    rng = np.random.default_rng(1)
    img = rng.integers(0, 255, (180, 320, 3), dtype=np.uint8)
    F = block_features(img)
    assert F.shape == (GRID[0] * GRID[1], 5)
    brighter = np.clip(img.astype(int) + 20, 0, 255).astype(np.uint8)
    # L minus frame median: a global brightness shift barely moves feature 0
    assert np.median(np.abs(block_features(brighter)[:, 0] - F[:, 0])) < 3.0


def test_pool_blocks_matches_direct_bs8():
    rng = np.random.default_rng(2)
    img = cv2_blur(rng.integers(0, 255, (180, 320, 3), dtype=np.uint8))
    direct = block_features(img, bs=8)                       # 22×40 grid
    pooled = pool_blocks(block_features(img, bs=4)[None])[0]  # 45×80 → 22×40
    assert pooled.shape == direct.shape == (22 * 40, 5)
    assert np.allclose(pooled, direct, atol=1e-2)
    assert grid_for(pooled.shape[0]) == (22, 40)


def cv2_blur(img):
    import cv2
    return cv2.GaussianBlur(img, (5, 5), 2)


def test_warp_small_identity():
    rng = np.random.default_rng(3)
    img = rng.integers(0, 255, (407, 720, 3), dtype=np.uint8)
    a = warp_small(img, np.eye(3), (407, 720))
    b = warp_small(img, None, (407, 720))
    assert a.shape == (180, 320, 3) and np.abs(a.astype(int) - b.astype(int)).max() <= 1


def test_flood_height_map_recovers_threshold_within_one_quantile_step():
    X, h, nb = _scene()
    M = fit_thr(X, h, nq=24)
    qs = np.unique(np.quantile(h, np.linspace(0.04, 0.96, 24)))
    step = np.max(np.diff(qs))
    assert np.all(M.acc[:nb] > 0.95)
    assert np.all(np.abs(M.thr[:nb] - 5.0) <= step)
    assert np.median(M.acc[nb:]) < 0.75          # noise blocks are not reliable
    # wet area at a stage: band blocks are under water above h*, dry below
    assert M.wet_at(6.5)[:nb].all() and not M.wet_at(4.0)[:nb].any()


def test_vote_separates_wet_and_dry_frames():
    X, h, _ = _scene()
    M = fit_thr(X[:300], h[:300])
    p, nsel = vote(M, X[300:], stage_grid(h[:300]))
    assert nsel >= 50
    above = h[300:] >= 5.0
    assert p[above].min() >= 4.7 and p[~above].max() <= 5.3


def test_kernel_ridge_recovers_linear_signal():
    rng = np.random.default_rng(4)
    n, B = 300, 100
    h = rng.uniform(0, 4, n)
    X = rng.normal(0, 1, (n, B, 5)).astype(np.float32)
    X[:, :20, 0] += h[:, None] * 3
    p = kernel_ridge(X[:200], h[:200], X[200:], lam=1.0)
    assert np.mean(np.abs(p - h[200:])) < 0.2


def test_scene_regressor_roi_fallback_and_sigma():
    X, h, nb = _scene()
    m = SceneRegressor(min_roi=50, sigma_folds=4).fit(X, h)
    assert m.n_roi >= nb and m.n_roi < X.shape[1]          # ROI chosen
    assert 0 < m.sigma < 1.5
    m2 = SceneRegressor(min_roi=10_000).fit(X, h)
    assert m2.n_roi == X.shape[1]                            # too few ROI blocks → all blocks


def test_causal_median_is_causal():
    t = pd.date_range("2026-10-01", periods=6, freq="1h", tz="UTC")
    p = np.array([1, 1, 1, 9, 1, 1], float)
    s = causal_median(t, p, "3h")
    assert s[2] == 1 and s[3] == 1                          # spike suppressed, nothing from the future
    s2 = causal_median(t, np.array([1, 2, 3, 4, 5, 100.0]), "3h")
    assert s2[4] == 4                                       # only t−2h..t used


def test_kalman_reduces_noise_and_handles_gaps():
    rng = np.random.default_rng(5)
    t = pd.date_range("2026-10-01", periods=200, freq="1h", tz="UTC")
    truth = np.full(200, 3.0)
    z = truth + rng.normal(0, 0.3, 200)
    z[50:60] = np.nan
    x, s = kalman_1d(t, z, q_per_h=1e-4, r=0.09)
    assert np.mean(np.abs(x[100:] - 3.0)) < 0.1 and np.all(np.isfinite(x))


def test_last_known_value():
    g = pd.Series(np.arange(10.0), index=pd.date_range("2026-10-01", periods=10, freq="1h", tz="UTC"))
    t = pd.DatetimeIndex([pd.Timestamp("2026-10-01 05:30", tz="UTC"), pd.Timestamp("2026-10-01 02:00", tz="UTC")])
    assert list(pv.last_known(t, g, "2h")) == [3.0, 0.0]
    assert np.isnan(pv.last_known(t, g, "24h")).all()


def test_site_metrics_and_verdict():
    t = pd.date_range("2026-10-04", periods=240, freq="1h", tz="UTC")
    h = 5 + np.where(np.arange(240) > 120, 1.0, 0.0)            # a 1 ft step → event frames
    gauge = pd.Series(np.r_[np.full(48, 5.0), h], index=pd.date_range(t[0] - pd.Timedelta("48h"), periods=288, freq="1h"))
    cam = h + 0.05
    r = pv.site_metrics(t, cam, h, gauge, calib_stage=np.linspace(4, 6, 100))
    assert abs(r["mae"] - 0.05) < 1e-9 and r["p1"]
    assert r["has_events"] and r["p2"] and r["mae_p24_ev"] > 0.9
    rows = [r] * 10 + [dict(r, p1=False, p2=False)] * 10
    v = pv.verdict(pd.DataFrame(rows), 0.957)
    assert v["verdict"] == "PARTIAL" and v["P1_sites"] == 10 and not v["P2"]   # 50 % < 70 %
    v = pv.verdict(pd.DataFrame([r] * 20), 0.957)
    assert v["verdict"] == "PASS"
    bad = dict(r, p1=False, p2=False)
    assert pv.verdict(pd.DataFrame([bad] * 20), 0.957)["verdict"] == "FAIL"
