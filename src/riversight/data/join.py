"""Join camera frames to gauge readings (the free ground truth)."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

import pandas as pd

from .nims import parse_filename


def frames_table(filenames: Iterable[str]) -> pd.DataFrame:
    rows = []
    for f in filenames:
        try:
            cam, dt = parse_filename(f)
        except ValueError:
            continue
        rows.append({"filename": f, "cam_id": cam, "time": pd.Timestamp(dt)})
    df = pd.DataFrame(rows, columns=["filename", "cam_id", "time"])
    return df.sort_values("time").reset_index(drop=True) if len(df) else df


def join_frames_to_stage(frames: pd.DataFrame, stage: pd.DataFrame, tolerance_min: float = 10.0,
                         interpolate: bool = True) -> pd.DataFrame:
    """Attach a gauge stage to every frame.

    If interpolate=True, linearly interpolate the gauge series at the frame time when the two
    bracketing readings are within `tolerance_min` of the frame; otherwise nearest within tolerance.
    Frames without a usable reading get NaN stage (kept, so coverage can be reported).
    """
    if not len(frames) or not len(stage):
        out = frames.copy()
        out["stage_ft"] = float("nan")
        out["stage_dt_min"] = float("nan")
        return out
    s = stage[["time", "value"]].dropna().sort_values("time").reset_index(drop=True)
    f = frames.sort_values("time").reset_index(drop=True)
    tol = pd.Timedelta(minutes=tolerance_min)
    if interpolate:
        # merge_asof both directions for bracketing readings
        prev = pd.merge_asof(f, s.rename(columns={"time": "t_prev", "value": "v_prev"}), left_on="time",
                             right_on="t_prev", direction="backward")
        nxt = pd.merge_asof(f, s.rename(columns={"time": "t_next", "value": "v_next"}), left_on="time",
                            right_on="t_next", direction="forward")
        out = prev.copy()
        out["t_next"], out["v_next"] = nxt["t_next"], nxt["v_next"]
        dt_prev = (out["time"] - out["t_prev"]).dt.total_seconds() / 60
        dt_next = (out["t_next"] - out["time"]).dt.total_seconds() / 60
        both = out["t_prev"].notna() & out["t_next"].notna() & (dt_prev <= tolerance_min) & (dt_next <= tolerance_min)
        span = (out["t_next"] - out["t_prev"]).dt.total_seconds()
        w = ((out["time"] - out["t_prev"]).dt.total_seconds() / span.where(span > 0, 1)).clip(0, 1)
        interp = out["v_prev"] + w * (out["v_next"] - out["v_prev"])
        nearest_prev = out["t_prev"].notna() & (dt_prev <= tolerance_min)
        nearest_next = out["t_next"].notna() & (dt_next <= tolerance_min)
        stage_ft = interp.where(both)
        stage_ft = stage_ft.where(both, out["v_prev"].where(nearest_prev & (~nearest_next | (dt_prev <= dt_next))))
        stage_ft = stage_ft.where(stage_ft.notna(), out["v_next"].where(nearest_next))
        out["stage_ft"] = stage_ft
        out["stage_dt_min"] = pd.concat([dt_prev.where(nearest_prev), dt_next.where(nearest_next)], axis=1).min(axis=1)
        return out[["filename", "cam_id", "time", "stage_ft", "stage_dt_min"]]
    m = pd.merge_asof(f, s.rename(columns={"value": "stage_ft", "time": "t_g"}), left_on="time", right_on="t_g",
                      direction="nearest", tolerance=tol)
    m["stage_dt_min"] = (m["time"] - m["t_g"]).abs().dt.total_seconds() / 60
    return m[["filename", "cam_id", "time", "stage_ft", "stage_dt_min"]]


def stage_variability(stage: pd.DataFrame) -> dict:
    """How much signal is there to measure? Used by site selection."""
    if not len(stage):
        return {"n": 0, "range_ft": 0.0, "std_ft": 0.0, "p95_p05_ft": 0.0}
    v = stage["value"]
    return {"n": int(len(v)), "range_ft": float(v.max() - v.min()), "std_ft": float(v.std()),
            "p95_p05_ft": float(v.quantile(0.95) - v.quantile(0.05))}
