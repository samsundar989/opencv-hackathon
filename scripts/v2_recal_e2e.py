"""W4 (D-0014 W4-1): end-to-end test of the weekly recalibration on real data, in a local store.

1. base = the site's v2 training set cut at 2026-10-03 (scripts/v2_recal_base.py --cut 2026-10-03);
2. the real Oct 3–14 frames (scene_kill30_test features + dino_live tokens) are replayed through
   recal.log_features exactly as the live cycle logs them, with their matched gauge;
3. recal.refit_site refits; base ∪ logged is the same frame set the served models/sites_v2/<cam> bundle was
   trained on, so the refit must reproduce it (weights, ROI, Kalman r) up to float rounding;
4. wall time and peak RSS are recorded, to size the weekly job on the m9g.large worker.

  python scripts/v2_recal_e2e.py --only TX_Tenmile_Ck_at_Parkinson_Rd_nr_Ferris   → results/v2/recal_e2e.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
DATA = Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))
CUT = pd.Timestamp("2026-10-03", tz="UTC")


def peak_rss_gb() -> float:
    try:
        import psutil
        p = psutil.Process()
        return round(max(p.memory_info().rss, getattr(p.memory_info(), "peak_wset", 0)) / 2 ** 30, 2)
    except Exception:
        return float("nan")


def run(cam: str) -> dict:
    from riversight.calib import recal as R
    from riversight.live.store import LocalStore
    from v2_export_bundles import training_set
    tmp = Path(tempfile.mkdtemp(prefix="recal_e2e_"))
    try:
        store = LocalStore(tmp / "s3")
        t, h, F, P, _ = training_set(cam)
        base = t < CUT
        import io
        b = io.BytesIO()
        np.savez_compressed(b, t=pd.DatetimeIndex(t[base]).as_unit("ns").asi8, h=h[base], F=F[base], P=P[base])
        store.put_bytes(R.BASE_KEY.format(cam=cam), b.getvalue())
        new = np.flatnonzero(~base)
        for i in new:                                          # replay what the cycle would have logged
            R.log_features(store, cam, t[i], F[i], P[i], float(h[i]), t[i], [], raw_ft=None)
        t0 = time.time()
        res = R.refit_site(store, cam, ROOT / "models" / "sites_v2", tmp / "out", min_new=1, now=t[-1])
        wall = time.time() - t0
        got = np.load(tmp / "out" / cam / "scene_model_v2.npz")
        ref = np.load(ROOT / "models" / "sites_v2" / cam / "scene_model_v2.npz")
        cmp = {k: float(np.max(np.abs(got[k].astype(float) - ref[k].astype(float)))) for k in ("w", "ym", "r", "q")
               if k in got and k in ref and got[k].shape == ref[k].shape}
        same_roi = bool(np.array_equal(got["roi"], ref["roi"])) and bool(np.array_equal(got["dino_roi"], ref["dino_roi"]))
        return {"cam_id": cam, "status": res["status"], "n_base": int(base.sum()), "n_logged": int(len(new)),
                "n_new_used": res.get("n_new"), "refit_wall_s": round(wall, 1), "peak_rss_gb": peak_rss_gb(),
                "max_abs_diff_vs_served_bundle": cmp, "same_roi": same_roi,
                "stage_max_before_ft": res.get("stage_max_before_ft"), "stage_max_after_ft": res.get("stage_max_after_ft")}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="+", default=["TX_Tenmile_Ck_at_Parkinson_Rd_nr_Ferris"])
    a = ap.parse_args()
    out = [run(c) for c in a.only]
    for o in out:
        print(json.dumps(o), flush=True)
    p = ROOT / "results" / "v2" / "recal_e2e.json"
    p.write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
