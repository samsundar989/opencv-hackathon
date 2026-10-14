import numpy as np
import pytest

from riversight.geometry.projective import ProjectiveModel, fit_isotonic_lookup, fit_linear, fit_robust


def _synth(n=200, a=-35.0, b=600.0, c=0.08, h_lo=1.0, h_hi=9.0, noise=1.5, outlier_frac=0.0, seed=1):
    rng = np.random.default_rng(seed)
    h = rng.uniform(h_lo, h_hi, n)
    m = ProjectiveModel(a, b, c)
    u = m.u(h) + rng.normal(0, noise, n)
    if outlier_frac:
        k = int(outlier_frac * n)
        idx = rng.choice(n, k, replace=False)
        u[idx] += rng.uniform(-150, 150, k)
    return h, u, m


def test_inverse_roundtrip():
    m = ProjectiveModel(-35.0, 600.0, 0.08)
    h = np.linspace(0, 12, 50)
    assert np.allclose(m.h(m.u(h)), h, atol=1e-9)


def test_linear_fit_recovers_parameters():
    h, u, true = _synth(noise=0.0)
    m = fit_linear(h, u)
    assert abs(m.a - true.a) < 1e-6 and abs(m.b - true.b) < 1e-6 and abs(m.c - true.c) < 1e-9


def test_robust_fit_ignores_outliers():
    h, u, true = _synth(noise=1.5, outlier_frac=0.3)
    m = fit_robust(h, u, inlier_px=6.0)
    hh = np.linspace(1, 9, 50)
    err_px = np.abs(m.u(hh) - true.u(hh)).max()
    assert err_px < 3.0, err_px
    # stage error from the inverse model at the noise level
    h_est = m.h(true.u(hh) + 1.5)
    assert np.nanmedian(np.abs(h_est - hh)) < 0.15
    assert m.n_inliers >= 0.6 * len(h)


def test_sensitivity_and_monotone():
    m = ProjectiveModel(-35.0, 600.0, 0.08)
    assert m.is_monotone_over(0, 12)
    s = m.sigma_h(5.0, sigma_u_px=2.0)
    assert 0 < s < 0.5  # ~2 px / (px per ft) should be a few hundredths to tenths of a foot
    bad = ProjectiveModel(-35.0, 600.0, -0.2)  # pole at h=5
    assert not bad.is_monotone_over(0, 12)


def test_robust_fit_needs_points():
    with pytest.raises(ValueError):
        fit_robust([1, 2], [3, 4])


def test_isotonic_lookup_monotone():
    h, u, _ = _synth(noise=2.0, n=600)
    hk, uk = fit_isotonic_lookup(h, u, n_bins=24)
    assert len(hk) >= 2
    assert np.all(np.diff(hk) >= 0)
    d = np.diff(uk)
    assert np.all(d <= 1e-9) or np.all(d >= -1e-9)  # monotone in one direction
