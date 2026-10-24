"""W4: fused stage (gauge when fresh, anchored camera Kalman when stale)."""
import numpy as np
import pandas as pd

from riversight.calib.fusion import R_GAUGE, Fused, anchor_bias, camera_r


def test_no_camera_holds_last_gauge_with_growing_sigma():
    F = Fused().gauge(0.0, 5.0)
    assert F.source == "gauge" and np.isclose(F.P, R_GAUGE)
    F.predict(6 * 3600.0, q_per_h=0.01)
    assert F.x == 5.0 and F.source == "last gauge" and np.isclose(F.P, R_GAUGE + 0.06)


def test_anchored_camera_tracks_change_not_bias():
    """Camera reads 0.5 ft high throughout; with the anchored offset the gap-fill follows the river's rise."""
    F = Fused().gauge(0.0, 5.0)
    F.b = 0.5
    for k in range(1, 25):                                    # river rises 0.05 ft/h; camera = truth + 0.5
        F.camera(k * 3600.0, 5.0 + 0.05 * k + 0.5, r=0.01, q_per_h=0.01)
    assert F.source == "camera gap-fill"
    assert abs(F.x - (5.0 + 0.05 * 24)) < 0.15
    G = Fused().gauge(0.0, 5.0)                               # without the anchor it drifts towards +0.5
    for k in range(1, 25):
        G.camera(k * 3600.0, 5.0 + 0.05 * k + 0.5, r=0.01, q_per_h=0.01)
    assert G.x - (5.0 + 0.05 * 24) > 0.3


def test_anchor_bias_window_and_minimum():
    t = pd.date_range("2026-05-01", periods=10, freq="6h", tz="UTC")
    z, h = np.arange(10.0) + 0.3, np.arange(10.0)
    t0 = t[-1] + pd.Timedelta("1h")
    assert np.isclose(anchor_bias(t, z, h, t0), 0.3)          # 8 frames inside the 48 h window
    assert anchor_bias(t[:2], z[:2], h[:2], t0) == 0.0        # too few / too old → no anchoring


def test_camera_r_whitens():
    rng = np.random.default_rng(0)
    white = rng.normal(scale=0.2, size=2000)
    assert np.isclose(camera_r(white), 0.04, rtol=0.1)
    red = np.convolve(rng.normal(size=2100), np.ones(20) / 20, "valid")[:2000]
    assert camera_r(red) < np.var(red)                        # autocorrelated residuals count as less noise
    assert np.isnan(camera_r(np.array([0.1, 0.2])))
