import numpy as np
import pandas as pd
import pytest

from riversight.killtest import ALIKED_ONNX, LIGHTGLUE_ONNX, CorrAccumulator, thin_frames, weighted_median


def test_corr_accumulator_matches_numpy():
    rng = np.random.default_rng(0)
    h = rng.normal(size=50)
    x = np.stack([h * 2 + rng.normal(size=50), rng.normal(size=50)], 1)  # pixel 0 correlated, pixel 1 not
    acc = CorrAccumulator()
    for k in range(50):
        acc.add(x[k].reshape(1, 2, 1), np.ones((1, 2), bool), float(h[k]))
    c = acc.corr()[0, :, 0]
    assert abs(c[0] - np.corrcoef(x[:, 0], h)[0, 1]) < 1e-9
    assert abs(c[1] - np.corrcoef(x[:, 1], h)[0, 1]) < 1e-9


def test_thin_frames_30min():
    t = pd.date_range("2026-10-01", periods=8, freq="15min", tz="UTC")
    out = thin_frames(pd.DataFrame({"time": t}), 30)
    assert list(out["time"]) == list(t[::2])


def test_weighted_median():
    assert weighted_median(np.array([1.0, 2.0, 100.0]), np.array([1.0, 1.0, 1.0])) == 2.0
    assert weighted_median(np.array([1.0, 2.0, 100.0]), np.array([0.1, 0.1, 5.0])) == 100.0


@pytest.mark.skipif(not (ALIKED_ONNX.exists() and LIGHTGLUE_ONNX.exists()), reason="ALIKED/LightGlue ONNX not downloaded")
def test_aliked_lightglue_registration_recovers_shift():
    """Bug (Oct 14): setPairInfo was called with the wrong signature; the 5.0 API takes keypoints + sizes."""
    import cv2
    from riversight.vision.register import Registrar

    rng = np.random.default_rng(3)
    ref = cv2.GaussianBlur(rng.integers(0, 255, (360, 480, 3), dtype=np.uint8), (5, 5), 0)
    H_true = np.array([[1, 0, 9.0], [0, 1, -5.0], [0, 0, 1]])
    frame = cv2.warpPerspective(ref, np.linalg.inv(H_true), (480, 360))
    r = Registrar(ALIKED_ONNX, LIGHTGLUE_ONNX)
    assert r.method == "aliked+lightglue"
    r.set_reference(ref)
    reg = r.register(frame)
    assert reg.ok, reg
    p = cv2.perspectiveTransform(np.float32([[[200, 150]]]), reg.H)[0, 0]
    q = cv2.perspectiveTransform(np.float32([[[200, 150]]]), H_true)[0, 0]
    assert np.linalg.norm(p - q) < 2.0
