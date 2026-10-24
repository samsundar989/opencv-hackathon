import importlib.util
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("compare_arms", ROOT / "bench" / "compare_arms.py")
ca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ca)


def test_psnr_identical_is_inf_and_known_value():
    a = np.zeros((4, 4), np.uint8)
    assert ca.psnr(a, a, 255.0) == float("inf")
    b = a.copy()
    b[0, 0] = 16                                   # mse = 256/16 = 16
    assert abs(ca.psnr(a, b, 255.0) - 10 * math.log10(255 ** 2 / 16)) < 1e-9


def test_equivalence_flags_diff_and_nan_stages():
    base = {"s1|resize_area": np.zeros((2, 2, 3), np.uint8), "s1|stage_pipeline": np.array([np.nan])}
    other = {"s1|resize_area": np.full((2, 2, 3), 2, np.uint8), "s1|stage_pipeline": np.array([np.nan])}
    e = ca.equivalence(base, other).set_index("stage")
    assert e.loc["resize_area", "max_abs_diff"] == 2
    assert e.loc["stage_pipeline", "max_abs_diff"] == 0.0     # both unregistered = equivalent


def test_cost_tables_cadences_cool_fee_and_break_even():
    fleet = pd.DataFrame({"arm": ["pip", "cool"], "threads": [2, 2], "fleet": [880, 880], "frames_per_s": [2.0, 2.5]})
    c, s = ca.cost_tables(fleet, ["pip", "cool"], {"ec2_usd_per_h": 0.1, "cool_usd_per_h": 0.005}, 2)
    c = c.set_index(["arm", "cadence_min"])
    assert c.loc[("pip", 30), "cameras_per_instance"] == 3600
    assert c.loc[("pip", 15), "cameras_per_instance"] == 1800
    assert abs(c.loc[("cool", 30), "break_even_speedup_vs_stock"] - 1.05) < 1e-9
    assert abs(c.loc[("pip", 30), "usd_per_camera_month"] - 1440 / 2.0 / 3600 * 0.1) < 1e-12
    assert abs(c.loc[("pip", 15), "usd_per_camera_month"] - 2 * c.loc[("pip", 30), "usd_per_camera_month"]) < 1e-12
    assert (s[s.arm == "pip"].instances == 1).all()
