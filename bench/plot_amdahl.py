"""Amdahl chart for a COOL benchmark run: where the per-frame time goes, per build (from amdahl.csv).

One 100 % stacked bar per arm: the learned matcher (ALIKED + LightGlue, OpenCV's DNN engine) vs every classical
stage together (decode, ORB + MAGSAC, warp, resize, Lab, Sobel, block features, ridge). Each segment is labelled
with its share and its mean milliseconds per call. Drawn with OpenCV 5's TrueType text API (`cv2.FontFace`).

    python bench/plot_amdahl.py results/cool_bench/<run>   → <run>/amdahl.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

S = 2                                           # render at 2x for print
SURFACE = (251, 252, 252)                       # #fcfcfb (BGR)
INK, INK2 = (11, 11, 11), (78, 81, 82)          # text primary / secondary
DNN_C = (214, 120, 42)                          # categorical slot 1, blue #2a78d6 (BGR)
CLS_C = (52, 104, 235)                          # categorical slot 2, orange #eb6834 (BGR)
DNN_STAGE = "register_aliked_lightglue_magsac"
ARM_NAMES = {"cool": "COOL G5 (OpenCV 5.1.0-dev)", "pip-5.0.0.93": "stock pip OpenCV 5.0.0.93"}


def text(img, s, x, y, size, color=INK):
    cv2.putText(img, s, (int(x * S), int(y * S)), color, cv2.FontFace("sans"), int(size * S))


def main() -> None:
    run = Path(sys.argv[1])
    am = pd.read_csv(run / "amdahl.csv")
    tmax = int(am.threads.max())
    am = am[am.threads == tmax]
    arms = [a for a in ("cool", "pip-5.0.0.93") if a in set(am.arm)] or sorted(am.arm.unique())

    W, H = 900, 150 + 70 * len(arms)
    L, R = 230, 30
    img = np.full((H * S, W * S, 3), SURFACE, np.uint8)
    text(img, "Where a frame's time goes (per-call means, both cores)", L - 210, 34, 17)
    text(img, "Every classical stage together is about 2 % of the time; COOL can only act on that part.",
         L - 210, 58, 12, INK2)

    y = 90
    for a in arms:
        d = am[am.arm == a]
        dnn = float(d[d.stage == DNN_STAGE].mean_ms.sum())
        cls = float(d[d.stage != DNN_STAGE].mean_ms.sum())
        tot = dnn + cls
        x0, x1 = L, W - R
        xs = x0 + (x1 - x0) * dnn / tot
        bar_h = 34
        cv2.rectangle(img, (x0 * S, y * S), (int(xs * S) - 2 * S, (y + bar_h) * S), DNN_C, -1)   # 2px surface gap
        cv2.rectangle(img, (int(xs * S), y * S), (x1 * S, (y + bar_h) * S), CLS_C, -1)
        text(img, ARM_NAMES.get(a, a), 20, y + 22, 12)
        text(img, f"DNN {100 * dnn / tot:.1f} %  ({dnn:.0f} ms)", x0 + 10, y + 23, 12, SURFACE)
        text(img, f"classical {100 * cls / tot:.1f} %  ({cls:.1f} ms)", x1 - 245, y + bar_h + 18, 11, INK2)
        y += 70

    ly = H - 34
    cv2.rectangle(img, (L * S, ly * S), ((L + 14) * S, (ly + 14) * S), DNN_C, -1)
    text(img, "ALIKED + LightGlue + MAGSAC (DNN engine)", L + 22, ly + 12, 11, INK2)
    cv2.rectangle(img, ((L + 330) * S, ly * S), ((L + 344) * S, (ly + 14) * S), CLS_C, -1)
    text(img, "classical: decode, ORB, warp, resize, Lab, Sobel, features", L + 352, ly + 12, 11, INK2)

    out = run / "amdahl.png"
    cv2.imwrite(str(out), img)
    print(out)


if __name__ == "__main__":
    main()
