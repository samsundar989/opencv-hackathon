"""Compare COOL benchmark arms run by bench/cool_bench.py on the same machine.

Reads <run>/<arm>/{kernels,fleet}.csv, outputs.npz, provenance.json and (optional) <run>/prices.json:
  {"instance": "m9g.large", "ec2_usd_per_h": ..., "cool_usd_per_h": ..., "source": "...", "date": "..."}
and writes into <run>/:
  compare_kernels.csv   per (threads, stage): p50 per arm, speedup = baseline p50 / arm p50
  amdahl.csv            each stage's share of the per-frame pipeline time, per arm (largest-thread regime)
  compare_fleet.csv     fleet cycles: frames/s per arm, speedup
  equivalence.csv       per stage: max |diff| and PSNR vs baseline, worst over sites; stage diff in ft
  cost.csv              $ per camera-month at 15- and 30-min cadences, cameras per instance, break-even speedup
  scaling.csv           cameras → cycle wall time, instances, $/month (whole-HIVIS-fleet curve)

    python bench/compare_arms.py results/cool_bench/<run> --baseline pip-5.0.0.93
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

CADENCES_MIN = (15, 30)                         # 15 = deployed timer; 30 = the original plan. Day and night counted
MONTH_H = 24 * 30                               # (conservative: the live worker skips night frames)
SCALING_CAMERAS = (20, 100, 250, 500, 880)
PIPE_STAGES = ["imdecode", "register_orb_magsac", "register_aliked_lightglue_magsac", "warpPerspective",
               "resize_area", "cvtColor_lab", "sobel_magnitude", "block_features", "ridge_predict"]


def psnr(a: np.ndarray, b: np.ndarray, peak: float) -> float:
    mse = float(np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2))
    return float("inf") if mse == 0 else 10 * math.log10(peak ** 2 / mse)


def equivalence(base: dict, other: dict) -> pd.DataFrame:
    rows = []
    for k in sorted(set(base) & set(other)):
        cam, stage = k.split("|")
        a, b = base[k], other[k]
        if a.shape != b.shape:
            rows.append({"stage": stage, "cam_id": cam, "max_abs_diff": np.nan, "psnr_db": np.nan, "shape_mismatch": True})
            continue
        d = float(np.nanmax(np.abs(a.astype(np.float64) - b.astype(np.float64)))) if a.size else 0.0
        if stage.startswith("stage") and np.isnan(a).all() and np.isnan(b).all():
            d = 0.0
        p = psnr(a, b, 255.0) if a.dtype == np.uint8 else np.nan
        rows.append({"stage": stage, "cam_id": cam, "max_abs_diff": d, "psnr_db": p, "shape_mismatch": False})
    return pd.DataFrame(rows)


def cost_tables(fleet: pd.DataFrame, arms: list[str], prices: dict, nproc_threads: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    big = fleet[(fleet.threads == nproc_threads) & (fleet.fleet == fleet.fleet.max())]
    fps = big.groupby("arm")["frames_per_s"].mean()
    rows, srows = [], []
    for arm in arms:
        cool = "cool" in arm.lower()
        usd_h = prices["ec2_usd_per_h"] + (prices.get("cool_usd_per_h", 0.0) if cool else 0.0)
        f = float(fps[arm])
        for cad in CADENCES_MIN:
            frames_month = MONTH_H * 60 / cad
            rows.append({"arm": arm, "cadence_min": cad, "instance": prices.get("instance"), "usd_per_h": usd_h,
                         "fleet_frames_per_s": f, "cameras_per_instance": math.floor(cad * 60 * f),
                         # compute-time share of the instance per camera (what a packed fleet pays)
                         "usd_per_camera_month": frames_month / f / 3600 * usd_h,
                         "break_even_speedup_vs_stock": (usd_h / prices["ec2_usd_per_h"]) if cool else 1.0})
            for n in SCALING_CAMERAS:
                inst = math.ceil(n / (cad * 60 * f))
                srows.append({"arm": arm, "cadence_min": cad, "cameras": n, "cycle_wall_s_one_instance": n / f,
                              "instances": inst, "usd_per_month": inst * MONTH_H * usd_h})
    return pd.DataFrame(rows), pd.DataFrame(srows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("--baseline", required=True)
    args = ap.parse_args()

    arms = sorted(p.name for p in args.run.iterdir() if (p / "kernels.csv").exists())
    if args.baseline not in arms:
        raise SystemExit(f"baseline {args.baseline} not in {arms}")
    # the arm is the directory name (the label inside the CSVs is whatever --arm said)
    K = pd.concat([pd.read_csv(args.run / a / "kernels.csv").assign(arm=a) for a in arms])
    F = pd.concat([pd.read_csv(args.run / a / "fleet.csv").assign(arm=a) for a in arms])

    piv = K.pivot_table(index=["threads", "stage"], columns="arm", values="p50_ms").reset_index()
    for a in arms:
        if a != args.baseline:
            piv[f"speedup_{a}"] = piv[args.baseline] / piv[a]
    piv.to_csv(args.run / "compare_kernels.csv", index=False, float_format="%.4f")

    tmax = int(K.threads.max())
    am = K[(K.threads == tmax) & K.stage.isin(PIPE_STAGES)].copy()
    am["share_of_stages"] = am["mean_ms"] / am.groupby("arm")["mean_ms"].transform("sum")
    am[["arm", "threads", "stage", "mean_ms", "share_of_stages"]].to_csv(args.run / "amdahl.csv", index=False,
                                                                        float_format="%.4f")

    fl = F.groupby(["threads", "fleet", "arm"])["frames_per_s"].mean().unstack("arm").reset_index()
    for a in arms:
        if a != args.baseline:
            fl[f"speedup_{a}"] = fl[a] / fl[args.baseline]
    fl.to_csv(args.run / "compare_fleet.csv", index=False, float_format="%.4f")

    base = dict(np.load(args.run / args.baseline / "outputs.npz"))
    eq = []
    for a in arms:
        if a == args.baseline:
            continue
        e = equivalence(base, dict(np.load(args.run / a / "outputs.npz")))
        g = e.groupby("stage").agg(max_abs_diff=("max_abs_diff", "max"), min_psnr_db=("psnr_db", "min"),
                                   sites=("cam_id", "nunique"), shape_mismatch=("shape_mismatch", "any")).reset_index()
        g.insert(0, "arm", a)
        eq.append(g)
    if eq:
        pd.concat(eq).to_csv(args.run / "equivalence.csv", index=False, float_format="%.6g")

    pf = args.run / "prices.json"
    if pf.exists():
        prices = json.loads(pf.read_text(encoding="utf-8"))
        c, s = cost_tables(F, arms, prices, tmax)
        c.to_csv(args.run / "cost.csv", index=False, float_format="%.6g")
        s.to_csv(args.run / "scaling.csv", index=False, float_format="%.6g")
    print(piv.to_string(index=False))
    print(fl.to_string(index=False))


if __name__ == "__main__":
    main()
