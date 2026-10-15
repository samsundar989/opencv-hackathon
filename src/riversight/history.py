"""SLICE_01B step 2: register a site's long history to its SLICE_01 reference, piecewise when the scene moved.

1. Every history frame is registered to the site's SLICE_01 reference with the same cascade
   (ORB → ALIKED+LightGlue → chained through the last good frame) and the same QA (sun-based night,
   homography plausibility).
2. Registration-failure runs: UTC days whose daylight success rate is < 30 % (≥ 3 daylight frames),
   merged when ≤ 2 days apart and kept when they span ≥ 3 days, are treated as "the scene changed"
   (camera moved/re-aimed, flood debris, construction).
3. For each run a segment reference is chosen inside it (sharpest daylight frame near the run's median
   stage) and the run's frames are registered to it. The segment reference is then registered to the main
   reference: if that link is good and plausible, frames get H = H_link · H_seg (same geometry as the
   test days, so they can train the model); if not, the segment is recorded as **unlinked** and its
   frames are excluded from training (a different view cannot calibrate the current one).
   Every run is logged in history/segments.csv — a camera-moved event is itself a QA-agent feature.

Outputs (data/derived/<cam>/history/): registration.parquet (one row per frame), segments.csv.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from riversight.killtest import (Cfg, homography_plausible, is_night, make_registrar, qa_registration,
                                 register_frames, sharpness, site_latlng)

FAIL_DAY_RATE = 0.30
MIN_DAY_FRAMES = 3
MIN_RUN_DAYS = 3
MERGE_GAP_DAYS = 2


def main_reference(data_dir: Path, cam: str) -> tuple[str, np.ndarray]:
    reg = pd.read_parquet(data_dir / "derived" / cam / "registration_cascade.parquet", columns=["ref"])
    name = reg["ref"].iloc[0]
    img = cv2.imread(str(data_dir / "raw" / "720" / cam / name))
    if img is None:
        raise FileNotFoundError(name)
    return name, img


def failure_runs(frames: pd.DataFrame, reg: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """[start_day, end_day] (inclusive) of multi-day registration-failure runs among daylight frames."""
    day = reg[~reg["night"].astype(bool)].join(frames["time"])
    if not len(day):
        return []
    g = day.groupby(day["time"].dt.floor("D"))["ok"].agg(["mean", "size"])
    bad = g[(g["size"] >= MIN_DAY_FRAMES) & (g["mean"] < FAIL_DAY_RATE)].index.sort_values()
    runs, cur = [], None
    for d in bad:
        if cur and (d - cur[1]).days <= MERGE_GAP_DAYS + 1:
            cur[1] = d
        else:
            if cur:
                runs.append(tuple(cur))
            cur = [d, d]
    if cur:
        runs.append(tuple(cur))
    return [r for r in runs if (r[1] - r[0]).days + 1 >= MIN_RUN_DAYS]


def _pick_segment_reference(frames: pd.DataFrame, cfg: Cfg, n_cand: int = 30):
    f = frames.dropna(subset=["stage_ft"])
    if not len(f):
        f = frames
    med = f["stage_ft"].median() if f["stage_ft"].notna().any() else 0.0
    order = (f["stage_ft"] - med).abs().fillna(0).sort_values().index[: max(n_cand, 1)]
    best, best_i, best_img = -1.0, None, None
    for i in order:
        img = cv2.imread(str(frames.loc[i, "path"]))
        if img is None or is_night(img, cfg):
            continue
        s = sharpness(img, cfg)
        if s > best:
            best, best_i, best_img = s, i, img
    return best_i, best_img


CHUNK = 300


def _register_chunked(frames: pd.DataFrame, ref: np.ndarray, cfg: Cfg, d: Path) -> pd.DataFrame:
    """register_frames in time-ordered chunks, each cached under history/reg_chunks/ so a preempted
    worker-q job resumes where it stopped. (Chained registration only loses its 'last good frame' at chunk
    boundaries; the direct ORB → ALIKED cascade is unaffected.)"""
    cdir = d / "reg_chunks"
    cdir.mkdir(parents=True, exist_ok=True)
    parts = []
    for k, s in enumerate(range(0, len(frames), CHUNK)):
        p = cdir / f"chunk_{k:04d}_{len(frames)}.pkl"
        if p.exists():
            parts.append(pd.read_pickle(p))
            continue
        part = register_frames(frames.iloc[s:s + CHUNK], ref, cfg, "cascade", progress=(0.0, 0.0))
        part.to_pickle(p.with_suffix(".tmp"))
        p.with_suffix(".tmp").replace(p)
        parts.append(part)
    return pd.concat(parts)


def register_history(data_dir: Path, cam: str, cfg: Cfg = Cfg(), progress=None) -> pd.DataFrame:
    d = data_dir / "derived" / cam / "history"
    out = d / "registration.parquet"
    if out.exists():
        return pd.read_parquet(out)
    frames = pd.read_parquet(d / "frames.parquet").sort_values("time").reset_index(drop=True)
    ref_name, ref = main_reference(data_dir, cam)
    shape = ref.shape[:2]
    latlng = site_latlng(data_dir, cam)
    raw = _register_chunked(frames, ref, cfg, d)
    reg = qa_registration(raw, frames, shape, latlng, cfg)
    reg["segment"] = "main"
    H_list, ok_list, seg_list = list(reg["H"]), list(reg["ok"].astype(bool)), list(reg["segment"])
    pos = {i: k for k, i in enumerate(reg.index)}
    seg_rows = []
    for k, (d0, d1) in enumerate(failure_runs(frames, reg)):
        in_run = (frames["time"] >= d0) & (frames["time"] < d1 + pd.Timedelta("1D"))
        fr = frames[in_run]
        si, simg = _pick_segment_reference(fr, cfg)
        row = {"segment": f"seg{k}", "start": d0.date().isoformat(), "end": d1.date().isoformat(),
               "n_frames": int(in_run.sum()), "main_ok_rate": float(reg.loc[in_run & ~reg["night"].astype(bool), "ok"].mean()),
               "seg_ref": frames.loc[si, "filename"] if si is not None else "", "linked": False, "link_inliers": 0,
               "seg_ok_rate": float("nan")}
        if simg is None or simg.shape[:2] != shape:
            seg_rows.append(row)
            continue
        link, link_ok = None, False
        for m in ("orb", "aliked"):
            R = make_registrar(cfg, m)
            R.set_reference(ref)
            r = R.register(simg)
            if r.ok and homography_plausible(r.H, shape, cfg.max_corner_frac, cfg.area_range)[0]:
                link, link_ok, row["link_inliers"] = r.H, True, r.n_inliers
                break
        sreg = qa_registration(register_frames(fr, simg, cfg, "cascade", progress=(0.8, 0.8)), fr, shape, latlng, cfg)
        day = ~sreg["night"].astype(bool)
        row["seg_ok_rate"] = float(sreg.loc[day, "ok"].mean()) if day.any() else float("nan")
        row["linked"] = link_ok
        for i in sreg.index[sreg["ok"]]:
            p = pos[i]
            if ok_list[p]:
                continue                     # already registered to the main reference directly
            Hs = np.array(sreg.loc[i, "H"]).reshape(3, 3)
            if link_ok:
                H_list[p], ok_list[p], seg_list[p] = (link @ Hs).ravel().tolist(), True, f"seg{k}"
            else:
                seg_list[p] = f"seg{k}-unlinked"
        seg_rows.append(row)
    reg["H"], reg["ok"], reg["segment"] = H_list, ok_list, seg_list
    reg = reg.join(frames[["filename"]]).assign(ref=ref_name)
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(seg_rows, columns=["segment", "start", "end", "n_frames", "main_ok_rate", "seg_ref", "linked",
                                    "link_inliers", "seg_ok_rate"]).to_csv(d / "segments.csv", index=False)
    reg.reset_index(drop=True).to_parquet(out)
    return reg


def load_registered_history(data_dir: Path, cam: str):
    """(registered daylight history frames with H, main reference image, reference filename) —
    the interface scripts/scene_features.py expects."""
    d = data_dir / "derived" / cam / "history"
    frames = pd.read_parquet(d / "frames.parquet").sort_values("time").reset_index(drop=True)
    reg = pd.read_parquet(d / "registration.parquet")
    f = frames.merge(reg[["filename", "ok", "H", "night", "segment"]], on="filename")
    f = f[f["ok"].astype(bool) & ~f["night"].astype(bool)]
    ref_name, ref = main_reference(data_dir, cam)
    return f, ref, ref_name
