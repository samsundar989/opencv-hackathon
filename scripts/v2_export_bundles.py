"""W4 step 5: export v2 shadow bundles → models/sites_v2/<cam>/ (scored beside v1 in the live cycle, not served).

Training data = the same frames as the v1 live models (scripts/export_site_models.load_all: history ∪ SLICE_01
30-day window incl. the test days, D-0008 ruling 5), with DINO tokens from dino_calib.npz ∪ dino_live.npz.
Configuration = `--config` (default: the configuration selected in results/v2/cv_summary.csv).

Files:
  models/sites_v2/dino_pca_basis.npz        fixed PCA basis (copy of results/v2/dino_pca_basis.npz)
  models/sites_v2/<cam>/scene_model_v2.npz  scene_v2.fit_bundle arrays (primal)
  models/sites_v2/<cam>/meta_v2.json        config, shas, σ from the v2 CV out-of-fold residuals, label

  workerq submit --project riversight --priority high --gpus 0 --ram 8 --cpus 4 -- python scripts/v2_export_bundles.py --jobs 3
"""
from __future__ import annotations

import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")

import argparse
import hashlib
import json
import shutil
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
DATA = Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))
OUT = ROOT / "models" / "sites_v2"
BASIS = ROOT / "results" / "v2" / "dino_pca_basis.npz"


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def cv_sigma(cam: str, config: str) -> float:
    p = DATA / "derived" / cam / "v2_cv.npz"
    if not p.exists():
        return float("nan")
    z = np.load(p)
    k = list(z["configs"]).index(config)
    ok = np.isfinite(z["P"][k])
    return float(np.std(z["P"][k][ok] - z["h"][ok])) if ok.sum() > 5 else float("nan")


def export_site(cam: str, site: dict, config: str, out_root: Path) -> str:
    from export_site_models import gauge_all, load_all
    from riversight.calib import scene_v2 as S
    from riversight.live.bundle import kalman_q
    from v2_cv import parse
    t, h, F, fns = load_all(cam)
    toks = {}
    for n in ("dino_calib.npz", "dino_live.npz"):
        z = np.load(DATA / "derived" / cam / n)
        for i, f in enumerate(z["filename"]):
            toks.setdefault(f, (n, i))
    Pz = {n: np.load(DATA / "derived" / cam / n)["P"] for n in ("dino_calib.npz", "dino_live.npz")}
    keep = np.array([f in toks for f in fns])
    t, h, F = t[keep], h[keep], F[keep]
    P = np.stack([Pz[toks[f][0]][toks[f][1]] for f, k in zip(fns, keep) if k])
    g = gauge_all(cam)
    arr = S.fit_bundle(F, P, t, h, parse(config), float(site["lat"]), float(site["lng"]), kalman_q(g.index, g.values))
    d, tmp = out_root / cam, out_root / f".{cam}.part"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    np.savez_compressed(tmp / "scene_model_v2.npz", **arr)
    meta = {"cam_id": cam, "lat": float(site["lat"]), "lon": float(site["lng"]), "config": config,
            "sigma_ft": round(cv_sigma(cam, config), 4), "n_train_frames": int(len(t)), "n_dropped_no_tokens": int((~keep).sum()),
            "n_roi_blocks": int(arr["roi"].sum()), "n_dino_patches": int(arr["dino_roi"].sum()) if "dino_roi" in arr else 0,
            "dino_onnx_sha256": __import__("riversight.vision.dino_features", fromlist=["x"]).MODEL_SHA256,
            "pca_basis_sha256": sha(BASIS), "model_sha": sha(tmp / "scene_model_v2.npz"),
            "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "label": "v2 candidate, SHADOW only (scored beside v1, never served unless D-0010 §2 is met); "
                     "live refit on all data incl. test days"}
    (tmp / "meta_v2.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    shutil.rmtree(d, ignore_errors=True)
    tmp.replace(d)
    return f"{cam}: {len(t)} frames, ROI {meta['n_roi_blocks']} blocks + {meta['n_dino_patches']} patches, σ {meta['sigma_ft']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", type=Path, default=DATA / "sites" / "kill_test.yaml")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--config")
    ap.add_argument("--jobs", type=int, default=3)
    a = ap.parse_args()
    config = a.config
    if not config:
        s = pd.read_csv(ROOT / "results" / "v2" / "cv_summary.csv")
        config = s.loc[s["selected"], "config"].iloc[0]
    print("config:", config, flush=True)
    sites = [s for s in yaml.safe_load(a.sites.read_text(encoding="utf-8"))["sites"] if not a.only or s["cam_id"] in a.only]
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy(BASIS, OUT / "dino_pca_basis.npz")
    fails = 0
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(export_site, s["cam_id"], s, config, OUT): s["cam_id"] for s in sites}
        for i, fu in enumerate(as_completed(futs)):
            p = os.environ.get("WORKERQ_PROGRESS")
            if p:
                Path(p).write_text(f"{(i + 1) / len(sites):.4f}")
            try:
                print(fu.result(), flush=True)
            except Exception:
                fails += 1
                print(f"{futs[fu]}: ERROR\n{traceback.format_exc()}", flush=True)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
