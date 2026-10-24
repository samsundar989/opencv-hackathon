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


@pytest.mark.parametrize("cfg", ["v1+dino_roi@0.5", "v1+dino_roi+norm@0.5+sun+rec120", "dino_roi+norm", "v1+sundoy"])
def test_shadow_bundle_primal_equals_cv_dual(tmp_path, cfg):
    """The live shadow bundle (primal) gives the same raw prediction as v2_cv's dual kernel ridge."""
    import json
    from riversight.calib.flood_height_map import fit_thr
    from v2_cv import parse
    rng = np.random.default_rng(7)
    n, m = 80, 6
    t = pd.date_range("2026-05-01 14:00", periods=n + m, freq="5h", tz="UTC")
    h = np.cumsum(rng.normal(scale=0.1, size=n + m)) + 3
    X = rng.normal(size=(n + m, 3600, 5)).astype(np.float32)
    X[:, :400, 0] += h[:, None]                                   # 400 blocks respond to stage
    P = rng.normal(size=(n + m, 448, 6)).astype(np.float32)
    P[:, :60, 1] += 2 * h[:, None]
    s = parse(cfg)
    arr = S.fit_bundle(X[:n], P[:n], t[:n], h[:n], s, 32.8, -96.8, q=0.01)
    np.savez(tmp_path / "scene_model_v2.npz", **arr)
    (tmp_path / "meta_v2.json").write_text(json.dumps({"lat": 32.8, "lon": -96.8}))
    sh = S.ShadowV2(tmp_path)
    got = np.array([sh.predict_raw(X[n + i], P[n + i], t[n + i]) for i in range(m)])
    # dual reference, written out the way scripts/v2_cv.run_site does it
    roi = fit_thr(X[:n], h[:n]).acc >= 0.80
    roi = roi if roi.sum() >= 50 else np.ones_like(roi)
    PP = S.scene_mean_removed(P) if s["norm"] else P
    Ktr, Kte = 0.0, 0.0
    if s["v1"] and s["w"] < 1:
        k = S.linear_kernel(X[:n][:, roi].reshape(n, -1), X[n:][:, roi].reshape(m, -1))
        Ktr, Kte = Ktr + (1 - s["w"]) * k[0], Kte + (1 - s["w"]) * k[1]
    if s["dino"]:
        sel = fit_thr(PP[:n], h[:n]).acc >= 0.80
        sel = sel if sel.sum() >= 10 else np.ones_like(sel)
        k = S.linear_kernel(PP[:n][:, sel].reshape(n, -1), PP[n:][:, sel].reshape(m, -1))
        Ktr, Kte = Ktr + s["w"] * k[0], Kte + s["w"] * k[1]
    p, loo = S.ridge_dual(Ktr, Kte, h[:n], 1.0, S.recency_weights(t[:n], s["tau"]) if s["tau"] else None)
    if s["sun"]:
        Z = S.nuisance_matrix(t, 32.8, -96.8, s["sun"] == "sundoy")
        p = p + S.nuisance_fit(Z[:n], loo, Z[n:])
    assert np.allclose(got, p, atol=1e-4)


def test_calib_frames_takes_h_from_the_cache_v1_used(tmp_path, monkeypatch):
    """Regression (Big Brook, Sand Ck): a frame with a failed history registration (H null) but a good 30-day
    cascade registration is a kill30_fit feature in v1, so its H must come from the cascade."""
    import v2_dino_features as V
    d = tmp_path / "derived" / "cam"
    (d / "history").mkdir(parents=True)
    t = pd.to_datetime(["2026-09-01 15:00", "2026-09-02 15:00"], utc=True).asi8
    np.savez(d / "scene_history_all.npz", filename=np.array(["a.jpg"]), t=t[:1])
    np.savez(d / "scene_kill30_fit.npz", filename=np.array(["a.jpg", "b.jpg"]), t=t)
    I, J = np.eye(3).ravel().tolist(), (np.eye(3) * 2).ravel().tolist()
    pd.DataFrame({"filename": ["a.jpg", "b.jpg"], "path": ["pa", "pb"]}).to_parquet(d / "history" / "frames.parquet")
    pd.DataFrame({"filename": ["a.jpg", "b.jpg"], "H": [I, None]}).to_parquet(d / "history" / "registration.parquet")
    pd.DataFrame({"filename": ["a.jpg", "b.jpg"], "path": ["pa", "pb"]}).to_parquet(d / "frames.parquet")
    pd.DataFrame({"filename": ["a.jpg", "b.jpg"], "H": [J, J]}).to_parquet(d / "registration_cascade.parquet")
    monkeypatch.setattr(V, "DATA", tmp_path)
    f = V.calib_frames("cam").set_index("filename")
    assert f.loc["a.jpg", "src"] == "hist" and np.allclose(f.loc["a.jpg", "H"], I)
    assert f.loc["b.jpg", "src"] == "k30" and np.allclose(f.loc["b.jpg", "H"], J)
