"""SLICE_01B step 5: demo assets from the scored models (run after scripts/scene_score.py).

  results/demo/floodheight_<cam>.jpg  reference frame (faces blurred) + h* colour map + legend in ft, best 5 sites
  results/demo/event_<cam>.gif        one event: registered frames, wet area drawn from the flood-height map
                                      at the camera's predicted stage (blocks with h* ≤ ŝ), stage needle camera vs gauge.
                                      Written natively by OpenCV 5 (cv2.imwriteanimation).

  python scripts/scene_demo.py [--sites N] [--gif-sites M]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DATA = Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))
RES = ROOT / "results"

from riversight import viz  # noqa: E402
from riversight.history import main_reference  # noqa: E402
from riversight.vision.privacy import blur_faces  # noqa: E402

W_OUT = 960


def overlay_hstar(ref: np.ndarray, M) -> np.ndarray:
    grid = tuple(M["grid"])
    h, w = ref.shape[:2]
    col = viz.floodheight_colour(M["thr"], M["acc"], grid, float(M["lo"]), float(M["hi"]), float(M["min_acc"]), (w, h))
    rel = cv2.resize((M["acc"].reshape(grid) >= float(M["min_acc"])).astype(np.float32), (w, h), interpolation=cv2.INTER_NEAREST)
    a = (0.6 * rel)[..., None]
    return (ref * (1 - a) + col * a).astype(np.uint8)


def floodheight_jpg(cam: str, M, out: Path) -> int:
    _, ref = main_reference(DATA, cam)
    ref, nf = blur_faces(ref)
    ref = cv2.resize(ref, (W_OUT, int(ref.shape[0] * W_OUT / ref.shape[1])), interpolation=cv2.INTER_CUBIC)
    over = overlay_hstar(ref, M)
    bar = viz.legend_bar(float(M["lo"]), float(M["hi"]), over.shape[0], 110)
    img = np.hstack([over, bar])
    top = np.full((40, img.shape[1], 3), 255, np.uint8)
    cv2.putText(top, f"{cam}: stage at which each patch goes under water (learned from the gauge, no survey)",
                (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.imwrite(str(out), np.vstack([top, img]), [cv2.IMWRITE_JPEG_QUALITY, 88])
    return nf


def needle_panel(h: int, lo: float, hi: float, gauge: float, camv: float, sigma: float, width: int = 150) -> np.ndarray:
    p = np.full((h, width, 3), 255, np.uint8)
    T, B = 30, h - 30
    Y = lambda v: int(T + (hi - v) / max(hi - lo, 1e-6) * (B - T))
    cv2.line(p, (60, T), (60, B), (120, 120, 120), 2)
    for v in viz._ticks(lo, hi, 6):
        cv2.line(p, (55, Y(v)), (65, Y(v)), (120, 120, 120), 1)
        cv2.putText(p, f"{v:.1f}", (8, Y(v) + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (90, 90, 90), 1, cv2.LINE_AA)
    if np.isfinite(sigma) and np.isfinite(camv):
        cv2.rectangle(p, (70, Y(camv + sigma)), (90, Y(camv - sigma)), viz.BAND, -1)
    if np.isfinite(camv):
        cv2.arrowedLine(p, (110, Y(camv)), (72, Y(camv)), viz.CAM, 3, tipLength=0.4)
    if np.isfinite(gauge):
        cv2.arrowedLine(p, (14, Y(gauge)), (52, Y(gauge)), viz.GAUGE, 2, tipLength=0.4)
    cv2.putText(p, "gauge", (4, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.4, viz.GAUGE, 1, cv2.LINE_AA)
    cv2.putText(p, "camera", (80, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.4, viz.CAM, 1, cv2.LINE_AA)
    cv2.putText(p, "ft", (64, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    return p


def event_gif(cam: str, M, out: Path, max_frames: int = 48) -> str:
    pred = pd.read_csv(RES / "kill_test_v2" / f"{cam}_pred.csv", parse_dates=["time"])
    if not pred["event"].any():
        return "no test-window event"
    # the event: the 36 h around the largest gauge excursion among event frames
    pk = pred.loc[pred.loc[pred["event"], "gauge_ft"].sub(pred["gauge_ft"].median()).abs().idxmax(), "time"]
    win = pred[(pred["time"] >= pk - pd.Timedelta("18h")) & (pred["time"] <= pk + pd.Timedelta("18h"))]
    if len(win) > max_frames:
        win = win.iloc[np.linspace(0, len(win) - 1, max_frames).astype(int)]
    reg = pd.read_parquet(DATA / "derived" / cam / "registration_cascade.parquet", columns=["filename", "H", "ok"])
    frames = pd.read_parquet(DATA / "derived" / cam / "frames.parquet", columns=["filename", "time", "path"])
    fn = dict(zip(pd.to_datetime(M["t"], utc=True), M["filename"]))
    _, ref = main_reference(DATA, cam)
    shape = ref.shape[:2]
    grid = tuple(M["grid"])
    lo, hi, sig = float(M["lo"]), float(M["hi"]), float(M["sigma"])
    lo, hi = min(lo, win["gauge_ft"].min(), win["camera_ft"].min()) - 0.2, max(hi, win["gauge_ft"].max(), win["camera_ft"].max()) + 0.2
    anim = cv2.Animation()
    imgs = []
    for _, r in win.iterrows():
        name = fn.get(r["time"])
        rr = reg[reg["filename"] == name]
        path = frames.loc[frames["filename"] == name, "path"]
        if name is None or not len(rr) or not len(path):
            continue
        img = cv2.imread(str(ROOT / path.iloc[0]))
        if img is None:
            continue
        img = cv2.warpPerspective(img, np.array(rr["H"].iloc[0]).reshape(3, 3), (shape[1], shape[0]), borderMode=cv2.BORDER_REPLICATE)
        img, _ = blur_faces(img)
        img = cv2.resize(img, (640, int(shape[0] * 640 / shape[1])), interpolation=cv2.INTER_AREA)
        s = float(r["camera_ft"])
        wet = ((M["acc"] >= float(M["min_acc"])) & (M["thr"] <= s)).reshape(grid).astype(np.uint8) if np.isfinite(s) else np.zeros(grid, np.uint8)
        mask = cv2.resize(wet * 255, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
        tint = img.copy()
        tint[mask > 0] = (0.45 * tint[mask > 0] + 0.55 * np.array([255, 120, 0])).astype(np.uint8)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(tint, cnts, -1, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(tint, f"{r['time']:%Y-%m-%d %H:%M}Z  camera {s:.2f} ft  gauge {r['gauge_ft']:.2f} ft",
                    (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(tint, "blue = predicted wet (h* <= camera stage)", (8, tint.shape[0] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        imgs.append(np.hstack([tint, needle_panel(tint.shape[0], lo, hi, float(r["gauge_ft"]), s, sig)]))
    if len(imgs) < 5:
        return f"only {len(imgs)} frames"
    anim.frames = imgs
    anim.durations = [350] * len(imgs)
    anim.loop_count = 0
    ok = cv2.imwriteanimation(str(out), anim)
    return f"{len(imgs)} frames, written={ok}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", type=int, default=5)
    ap.add_argument("--gif-sites", type=int, default=2)
    a = ap.parse_args()
    df = pd.read_csv(RES / "kill_test_v2.csv")
    df = df[df["tier"] != "C"].dropna(subset=["nmae"]).sort_values("nmae")
    out = RES / "demo"
    out.mkdir(parents=True, exist_ok=True)
    picked = [c for c in df["cam_id"] if (DATA / "derived" / c / "final_model.npz").exists()][: a.sites]
    for cam in picked:
        M = np.load(DATA / "derived" / cam / "final_model.npz", allow_pickle=False)
        nf = floodheight_jpg(cam, M, out / f"floodheight_{cam}.jpg")
        print(f"floodheight_{cam}.jpg ({nf} faces blurred)")
    ev = df[df["n_ev"] >= 3]
    done = 0
    for cam in [c for c in ev["cam_id"] if c in picked] + [c for c in ev["cam_id"] if c not in picked]:
        if done >= a.gif_sites:
            break
        M = np.load(DATA / "derived" / cam / "final_model.npz", allow_pickle=False)
        msg = event_gif(cam, M, out / f"event_{cam}.gif")
        print(f"event_{cam}.gif: {msg}")
        done += msg.endswith("True")


if __name__ == "__main__":
    main()
