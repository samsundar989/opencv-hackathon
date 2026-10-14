import cv2
import numpy as np

from riversight.vision.register import Registrar, warp_to_reference
from riversight.vision.transect import Transect, detect_transition, profile_features, sample_profile


def _river_scene(waterline_y=120, h=200, w=320, seed=0):
    """Synthetic bank: textured 'land' above the waterline, smooth darker 'water' below."""
    rng = np.random.default_rng(seed)
    img = np.zeros((h, w, 3), np.uint8)
    land = rng.integers(90, 200, (waterline_y, w, 3), dtype=np.uint8)
    img[:waterline_y] = land
    water = np.full((h - waterline_y, w, 3), (120, 90, 60), np.uint8) + rng.integers(0, 6, (h - waterline_y, w, 3), dtype=np.uint8)
    img[waterline_y:] = water
    return img


def test_opencv_is_5():
    assert cv2.__version__.startswith("5."), cv2.__version__
    assert hasattr(cv2, "USAC_MAGSAC")


def test_transect_sampling_length():
    t = Transect("t", np.array([[10, 10], [10, 110]], np.float32), half_width=2)
    s, v = sample_profile(np.zeros((200, 200), np.uint8), t)
    assert abs(t.length - 100) < 1e-6 and len(s) == 101 and v.shape == (101, 1)


def test_detect_transition_on_synthetic_bank():
    img = _river_scene(waterline_y=120)
    t = Transect("t", np.array([[160, 20], [160, 190]], np.float32), half_width=3)  # land (top) → water (bottom)
    feats = profile_features(img, t)
    s, conf = detect_transition(feats)
    assert abs((20 + s) - 120) <= 3, (s, conf)
    assert conf > 0.3


def test_orb_registration_recovers_shift():
    rng = np.random.default_rng(3)
    ref = rng.integers(0, 255, (240, 320, 3), dtype=np.uint8)
    ref = cv2.GaussianBlur(ref, (3, 3), 0)
    H_true = np.array([[1, 0, 7.0], [0, 1, -4.0], [0, 0, 1]])
    frame = cv2.warpPerspective(ref, np.linalg.inv(H_true), (320, 240))
    r = Registrar(use_aliked=False)
    assert r.set_reference(ref) > 50
    reg = r.register(frame)
    assert reg.ok, reg
    # map the frame's origin-ish point back and compare to truth
    p = cv2.perspectiveTransform(np.float32([[[100, 100]]]), reg.H)[0, 0]
    q = cv2.perspectiveTransform(np.float32([[[100, 100]]]), H_true)[0, 0]
    assert np.linalg.norm(p - q) < 1.5
    back = warp_to_reference(frame, reg.H, ref.shape[:2])
    assert back.shape == ref.shape


def test_detect_changepoint_either_direction():
    from riversight.vision.transect import detect_changepoint
    img = _river_scene(waterline_y=120)
    down = Transect("down", np.array([[160, 20], [160, 190]], np.float32), half_width=3)
    up = Transect("up", np.array([[160, 190], [160, 20]], np.float32), half_width=3)
    s1, c1 = detect_changepoint(profile_features(img, down))
    s2, c2 = detect_changepoint(profile_features(img, up))
    assert abs((20 + s1) - 120) <= 3 and abs((190 - s2) - 120) <= 3, (s1, s2)
    assert c1 > 0.3 and c2 > 0.3
