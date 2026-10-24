"""W4: DINOv2 in cv2.dnn matches onnxruntime; v2 ridge/LOO/nuisance algebra; solar position; config parsing."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from riversight.calib import scene_v2 as S
from riversight.vision import dino_features as D

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

needs_model = pytest.mark.skipif(not D.MODEL.exists(), reason="models/onnx/dinov2_small_224x392.onnx not built "
                                 "(scripts/v2_export_dino.py)")


@needs_model
def test_dino_cv2dnn_matches_onnxruntime():
    ort = pytest.importorskip("onnxruntime")
    assert D.sha256(D.MODEL) == D.MODEL_SHA256
    rng = np.random.default_rng(0)
    small = rng.integers(0, 256, (180, 320, 3), dtype=np.uint8)
    b = D.blob(small)
    rgb = __import__("cv2").resize(small, (D.IN_W, D.IN_H))[:, :, ::-1].astype(np.float32) / 255
    manual = ((rgb - np.array(D.MEAN)) / np.array(D.STD)).transpose(2, 0, 1)[None]
    assert np.abs(b - manual).max() < 1e-5                          # blobFromImageWithParams = ImageNet norm
    sess = ort.InferenceSession(str(D.MODEL), providers=["CPUExecutionProvider"])
    ref = sess.run(None, {"pixel_values": b})[0].reshape(-1, D.DIM)
    for engine in ("auto", "new"):
        got = D.tokens(D.load_net(engine=engine), small)
        assert got.shape == (1 + D.PGRID[0] * D.PGRID[1], D.DIM)
        assert np.abs(got - ref).max() < 1e-3, engine


def test_patch_of_block_covers_grid():
    p = D.patch_of_block()
    assert p.shape == (45 * 80,) and p.min() == 0 and p.max() == 16 * 28 - 1
    assert len(np.unique(p)) == 16 * 28                              # every patch holds some v1 block


def _toy(n=60, d=7, seed=1):
    rng = np.random.default_rng(seed)
    A = rng.normal(size=(n + 10, d))
    y = A[:, 0] * 2 + rng.normal(scale=0.3, size=n + 10)
    K, Kb = S.linear_kernel(A[:n], A[n:])
    return K, Kb, y[:n]


def test_weighted_ridge_unit_weights_equal_unweighted():
    K, Kb, y = _toy()
    p0, l0 = S.ridge_dual(K, Kb, y, 1.0)
    p1, l1 = S.ridge_dual(K, Kb, y, 1.0, np.ones(len(y)))
    assert np.allclose(p0, p1) and np.allclose(l0, l1)


def test_v1_config_reproduces_scene_tune_ridge():
    from scene_tune import _eig_ridge
    rng = np.random.default_rng(3)
    A = rng.normal(size=(50, 40)).astype(np.float32)
    y = rng.normal(size=40)
    p0, l0 = _eig_ridge(A[:40], A[40:], y)(1.0)
    p1, l1 = S.ridge_dual(*S.linear_kernel(A[:40], A[40:]), y, 1.0)
    assert np.allclose(p0, p1) and np.allclose(l0, l1)


def test_weighted_loo_is_exact():
    """eᵢ = αᵢ/[(K+Λ)⁻¹]ᵢᵢ equals refitting without frame i (weighted mean held fixed, as in the formula)."""
    K, _, y = _toy(n=30)
    sw = np.linspace(0.2, 1.0, 30)
    _, loo = S.ridge_dual(K, K[:1], y, 1.0, sw)
    ym = np.sum(sw * y) / np.sum(sw)
    c = 0.05
    for i in (0, 11, 29):
        m = np.arange(30) != i
        a = np.linalg.solve(K[np.ix_(m, m)] + np.diag(c / sw[m]), y[m] - ym)
        assert np.isclose(y[i] - (K[i, m] @ a + ym), loo[i])


def test_nuisance_fit_removes_sun_bias():
    rng = np.random.default_rng(4)
    t = pd.date_range("2026-06-01 13:00", periods=200, freq="47min", tz="UTC")
    Z = S.nuisance_matrix(t, 32.5, -96.7)
    e = 0.02 * Z[:, 0] + rng.normal(scale=0.01, size=200)          # residual grows with sun elevation
    bias = S.nuisance_fit(Z[:150], e[:150], Z[150:], lam=1e-3)
    assert np.mean(np.abs(e[150:] - bias)) < 0.5 * np.mean(np.abs(e[150:] - e[:150].mean()))


def test_solar_position_sane():
    # Dallas, 2026-06-21 18:30 UTC ≈ solar noon: elevation ≈ 90 − 32.8 + 23.4 ≈ 80.6°, sun to the south
    el, az = S.solar_position(pd.DatetimeIndex(["2026-06-21 18:30"], tz="UTC"), 32.8, -96.8)
    assert 78 < el[0] < 82 and 150 < az[0] < 210
    el, _ = S.solar_position(pd.DatetimeIndex(["2026-06-21 08:00"], tz="UTC"), 32.8, -96.8)
    assert el[0] < 0                                                  # 3 am local


def test_scene_mean_removed_is_affine_exact():
    rng = np.random.default_rng(5)
    T = rng.normal(size=(3, 448, 384)).astype(np.float32)
    basis = {"mean": rng.normal(size=384).astype(np.float32), "components": rng.normal(size=(8, 384)).astype(np.float32)}
    a = S.scene_mean_removed(D.project(T, basis))
    b = D.project(T - T.mean(1, keepdims=True), {"mean": np.zeros(384, np.float32), "components": basis["components"]})
    assert np.allclose(a, b, atol=1e-3)


def test_config_parse():
    from v2_cv import CONFIGS, parse
    assert parse("v1") == {"v1": True, "dino": None, "w": 0.0, "norm": False, "sun": None, "tau": None}
    assert parse("dino_roi")["w"] == 1.0
    p = parse("v1+dino_roi+norm@0.5+sun+rec120")
    assert p == {"v1": True, "dino": "dino_roi", "w": 0.5, "norm": True, "sun": "sun", "tau": 120.0}
    assert len(set(CONFIGS)) == len(CONFIGS) and CONFIGS[0] == "v1"
