"""W1: live model bundle — primal ridge = dual ridge, arm-safe warp = training warp, stepwise Kalman =
batch Kalman, and (when the local data cache exists) a protocol-cut bundle reproduces scene_score."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from riversight.calib.scene_regressor import kalman_1d
from riversight.live.bundle import KalmanState, SiteModel, fit_ridge_primal, warp_small_safe
from riversight.vision.scene_features import warp_small

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def test_primal_ridge_matches_dual():
    from scene_tune import _eig_ridge
    rng = np.random.default_rng(0)
    A, B = rng.normal(size=(120, 300)).astype(np.float32), rng.normal(size=(15, 300)).astype(np.float32)
    y = A[:, :5].sum(1) + rng.normal(0, 0.1, 120)
    dual, loo_d = _eig_ridge(A, B, y)(1.0)
    mu, sd, w, ym, loo = fit_ridge_primal(A, y, 1.0)
    primal = ((B - mu) / sd).astype(np.float64) @ w + ym
    assert np.allclose(primal, dual, atol=1e-6)
    assert np.allclose(loo, loo_d, atol=1e-9)


def test_warp_small_safe_matches_replicate_warp():
    rng = np.random.default_rng(1)
    img = cv2_blur(rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8))
    H = np.array([[1.01, 0.004, -9.0], [-0.003, 0.995, 6.0], [1e-6, -2e-6, 1.0]])
    a = warp_small(img, H, (720, 1280)).astype(int)
    b = warp_small_safe(img, H, (720, 1280)).astype(int)
    assert np.abs(a - b).max() <= 1


def cv2_blur(img):
    import cv2
    return cv2.GaussianBlur(img, (9, 9), 3)


def test_kalman_step_matches_batch(tmp_path):
    rng = np.random.default_rng(2)
    t = pd.DatetimeIndex(pd.Timestamp("2026-10-01", tz="UTC") + pd.to_timedelta(np.sort(rng.uniform(0, 72, 40)), "h"))
    z = 5 + np.cumsum(rng.normal(0, 0.05, 40))
    z[7] = np.nan
    xs, ss = kalman_1d(t, z, 0.01, 0.04)
    m = SiteModel.__new__(SiteModel)
    m.a = {"q": np.float64(0.01), "r": np.float64(0.04)}
    s, out, sig = KalmanState(), [], []
    for ti, zi in zip(t, z):
        s, x, sg = m.kalman_step(KalmanState.from_json(s.to_json()), ti.timestamp(), zi)   # survives JSON
        out.append(x)
        sig.append(sg)
    assert np.allclose(out, xs) and np.allclose(sig, ss)


CAM = "NJ_Big_Brook_near_Marlboro"
DATA = ROOT / "data" / "derived" / CAM


@pytest.mark.skipif(not (DATA / "final_model.npz").exists(), reason="local data cache not present")
def test_protocol_cut_bundle_reproduces_scene_score(tmp_path):
    import hashlib
    import json
    import yaml
    spec = importlib.util.spec_from_file_location("export_site_models", ROOT / "scripts" / "export_site_models.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    cfg = json.loads(ex.FROZEN.read_text(encoding="utf-8"))
    site = next(s for s in yaml.safe_load((ROOT / "data" / "sites" / "kill_test.yaml").read_text())["sites"]
                if s["cam_id"] == CAM)
    ex.export_site(CAM, site, cfg, hashlib.sha256(b"").hexdigest(), {}, tmp_path, cut="2026-10-03")
    m = SiteModel(tmp_path / CAM)
    z = np.load(DATA / "scene_kill30_test.npz")
    fm = np.load(DATA / "final_model.npz")
    raw = m.predict_raw(z["F"][:10].astype(np.float32))
    s, out = KalmanState(), []
    for ti, zi in zip(pd.to_datetime(z["t"][:10], utc=True), raw):
        s, x, _ = m.kalman_step(s, ti.timestamp(), zi)
        out.append(x)
    assert np.allclose(out, fm["pred"][:10], atol=1e-4)
    assert set(json.loads((tmp_path / CAM / "meta.json").read_text())) >= {
        "cam_id", "nwis_id", "lat", "lon", "tier", "sigma_ft", "calib_start", "calib_end", "n_calib_frames",
        "stage_p05", "stage_p50", "stage_p90", "stage_p95", "frozen_config_sha", "model_sha", "trained_at"}


def test_connected_inundation_ignores_disconnected_blocks():
    from riversight.live.bundle import connected_inundation, inundation_seed
    rows, cols = 45, 80
    thr = np.full(rows * cols, 9.0)
    acc = np.zeros(rows * cols)
    g = thr.reshape(rows, cols)
    a = acc.reshape(rows, cols)
    a[30:45, 10:60] = 0.95                         # river corridor, low in the frame
    g[40:45, 10:60] = 1.0                          # water's edge at typical stage
    g[30:40, 10:60] = 3.0                          # bank floods at 3 ft
    a[2:6, 60:66] = 0.95                           # reliable speck on the hillside / sky
    g[2:6, 60:66] = 1.0
    seed = inundation_seed(thr, acc, 0.8, (rows, cols))
    assert seed[42, 20] and not seed[3, 62]
    wet2 = connected_inundation(thr, acc, 0.8, 2.0, seed, (rows, cols))
    wet4 = connected_inundation(thr, acc, 0.8, 4.0, seed, (rows, cols))
    assert wet2[42, 20] and not wet2[35, 20] and not wet2[3, 62]
    assert wet4[35, 20] and not wet4[3, 62]
