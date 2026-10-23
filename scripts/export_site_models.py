"""SPRINT W1 step 1: export one live model bundle per kill-test site (INTERFACES §1) → models/sites/<cam>/.

Live models are refit with the frozen D-0007 setting on **all** registered daylight frames we have
(history + the SLICE_01 30-day window, test days included). They are labelled "live models"; the
reported numbers stay the frozen-protocol ones (D-0008 ruling 5).

Per site:
  * training set = scene_history_all ∪ scene_kill30_fit ∪ scene_kill30_test (deduplicated by filename);
  * flood-height map + ROI + primal ridge weights (live.bundle.fit_scene_model), Kalman q from the gauge;
  * σ = the frozen setting's forward-chaining out-of-fold residual std (tune_cv.npz), tier from kill_test_v2.csv;
  * quality p-levels (lap_var p5, fog_score p95) over ≤ 300 sampled training frames;
  * extra references: every view-change segment in history/segments.csv, with its link H when linkable.

  workerq submit --project riversight --priority high --gpus 0 --ram 6 --cpus 2 --node local -- \
    C:/Users/samsu/AppData/Local/Python/pythoncore-3.14-64/python.exe scripts/export_site_models.py --jobs 2
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
DATA = Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))
OUT = ROOT / "models" / "sites"
FROZEN = ROOT / "results" / "scene" / "frozen_config.json"
SOURCES = ("scene_history_all.npz", "scene_kill30_fit.npz", "scene_kill30_test.npz")


def load_all(cam: str, cut: pd.Timestamp | None = None):
    """(t, h, F float16) over every cached feature file, time-sorted, deduplicated by filename."""
    metas, feats = [], []
    for name in SOURCES:
        p = DATA / "derived" / cam / name
        if p.exists():
            z = np.load(p)
            metas.append(pd.DataFrame({"t": z["t"], "h": z["h"], "fn": z["filename"], "src": len(feats),
                                       "k": np.arange(len(z["t"]))}))
            feats.append(z["F"])
    df = pd.concat(metas, ignore_index=True)
    df["t"] = pd.to_datetime(df["t"], utc=True)
    df = df[np.isfinite(df["h"])]
    if cut is not None:
        df = df[df["t"] < cut]
    df = df.drop_duplicates("fn").sort_values("t").reset_index(drop=True)
    F = np.stack([feats[s][k] for s, k in zip(df["src"], df["k"])])
    return pd.DatetimeIndex(df["t"]), df["h"].to_numpy(float), F, df["fn"].tolist()


def gauge_all(cam: str) -> pd.Series:
    parts = []
    for p in (DATA / "derived" / cam / "history" / "stage.parquet", DATA / "derived" / cam / "stage.parquet"):
        if p.exists():
            s = pd.read_parquet(p)
            parts.append(pd.Series(s["value"].to_numpy(float), index=pd.DatetimeIndex(s["time"])))
    g = pd.concat(parts).sort_index()
    return g[~g.index.duplicated(keep="last")]


def frozen_sigma(cam: str, cfg: dict) -> float:
    p = DATA / "derived" / cam / "tune_cv.npz"
    if not p.exists():
        return float("nan")
    z = np.load(p)
    k = list(z["keys"]).index(f"{cfg['bs']}|{cfg['thr']}|{cfg['lam']}|{cfg['smooth']}")
    oof, h = z["P"][k], z["h"]
    ok = np.isfinite(oof)
    return float(np.std(oof[ok] - h[ok])) if ok.sum() > 5 else float("nan")


def quality_levels(cam: str, fns: list[str], n: int = 300) -> dict:
    import cv2
    from riversight.live.quality import image_quality
    pick = [fns[i] for i in np.linspace(0, len(fns) - 1, min(n, len(fns))).astype(int)]
    rows = []
    for fn in pick:
        img = cv2.imread(str(DATA / "raw" / "720" / cam / fn))
        if img is not None:
            rows.append(image_quality(img))
    q = pd.DataFrame(rows)
    return {"n": len(q), "lap_var_p5": float(q["lap_var"].quantile(0.05)), "fog_p95": float(q["fog_score"].quantile(0.95)),
            "glare_p95": float(q["glare_frac"].quantile(0.95)), "mean_v_p5": float(q["mean_v"].quantile(0.05))}


def extra_references(cam: str, ref, d: Path) -> list[dict]:
    """Copy each view-change segment reference; re-derive its link H to the main reference when it links."""
    import cv2
    from riversight.killtest import Cfg, homography_plausible, make_registrar
    p = DATA / "derived" / cam / "history" / "segments.csv"
    if not p.exists():
        return []
    cfg, out = Cfg(), []
    for _, s in pd.read_csv(p).iterrows():
        if not isinstance(s["seg_ref"], str) or not s["seg_ref"]:
            continue
        img = cv2.imread(str(DATA / "raw" / "720" / cam / s["seg_ref"]))
        if img is None:
            continue
        name = f"reference_{s['start'].replace('-', '')}.jpg"
        cv2.imwrite(str(d / name), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        H = None
        if bool(s["linked"]) and img.shape[:2] == ref.shape[:2]:
            for m in ("orb", "aliked"):
                R = make_registrar(cfg, m)
                R.set_reference(ref)
                r = R.register(img)
                if r.ok and homography_plausible(r.H, ref.shape[:2], cfg.max_corner_frac, cfg.area_range)[0]:
                    H = r.H.ravel().tolist()
                    break
        out.append({"file": name, "segment": s["segment"], "start": s["start"], "end": s["end"],
                    "linked": H is not None, "H_to_main": H, "source": s["seg_ref"]})
    return out


def export_site(cam: str, site: dict, cfg: dict, cfg_sha: str, tiers: dict, out_root: Path,
                cut: str | None = None) -> str:
    import cv2
    cv2.setNumThreads(2)
    from riversight.live.bundle import fit_scene_model, hstar_json, kalman_q, sha_file
    d = out_root / cam
    tmp = out_root / f".{cam}.part"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    cut_ts = pd.Timestamp(cut, tz="UTC") if cut else None
    t, h, F, fns = load_all(cam, cut_ts)
    g = gauge_all(cam)
    if cut_ts is not None:
        g = g[g.index < cut_ts]
    arr = fit_scene_model(F, h, cfg, kalman_q(g.index, g.values))
    ref_name = pd.read_parquet(DATA / "derived" / cam / "registration_cascade.parquet", columns=["ref"])["ref"].iloc[0]
    ref = cv2.imread(str(DATA / "raw" / "720" / cam / ref_name))
    cv2.imwrite(str(tmp / "reference.jpg"), ref, [cv2.IMWRITE_JPEG_QUALITY, 95])
    np.savez_compressed(tmp / "scene_model.npz", **arr)
    lo, hi = float(np.quantile(h, 0.04)), float(np.quantile(h, 0.96))
    (tmp / "hstar.json").write_text(json.dumps(hstar_json(arr, lo, hi)), encoding="utf-8")
    extras = extra_references(cam, ref, tmp)
    meta = {
        "cam_id": cam, "nwis_id": str(site["nwis_id"]), "lat": float(site["lat"]), "lon": float(site["lng"]),
        "state": site.get("state"), "tier": tiers.get(cam, "C"), "sigma_ft": round(frozen_sigma(cam, cfg), 4),
        "calib_start": t[0].isoformat(), "calib_end": t[-1].isoformat(), "n_calib_frames": int(len(t)),
        **{f"stage_p{q:02d}": round(float(np.quantile(h, q / 100)), 3) for q in (5, 50, 90, 95)},
        "stage_min": round(float(h.min()), 3), "stage_max": round(float(h.max()), 3),
        "flood_elevated_ft": round(float(np.quantile(h, 0.90)), 3), "flood_ft": round(float(np.quantile(h, 0.99)), 3),
        "n_roi_blocks": int(arr["roi"].sum()), "ref_shape": list(ref.shape[:2]), "reference": ref_name,
        "extra_references": extras, "quality": quality_levels(cam, fns),
        "frozen_config_sha": cfg_sha, "model_sha": sha_file(tmp / "scene_model.npz"),
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label": "live model (refit on all data incl. test days; not the frozen-protocol numbers)" if not cut
                 else f"protocol-cut model (training < {cut})",
    }
    (tmp / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    shutil.rmtree(d, ignore_errors=True)
    tmp.replace(d)
    return f"{cam}: {len(t)} frames, ROI {meta["n_roi_blocks"]}, sigma {meta['sigma_ft']}, {len(extras)} extra refs"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", type=Path, default=DATA / "sites" / "kill_test.yaml")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--cut", help="train only on frames before this UTC date (round-trip test vs scene_score)")
    a = ap.parse_args()
    cfg = json.loads(FROZEN.read_text(encoding="utf-8"))
    cfg_sha = hashlib.sha256(FROZEN.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    tiers = dict(pd.read_csv(ROOT / "results" / "kill_test_v2.csv")[["cam_id", "tier"]].values)
    sites = [s for s in yaml.safe_load(a.sites.read_text(encoding="utf-8"))["sites"] if not a.only or s["cam_id"] in a.only]
    a.out.mkdir(parents=True, exist_ok=True)
    done, fails = 0, 0
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(export_site, s["cam_id"], s, cfg, cfg_sha, tiers, a.out, a.cut): s["cam_id"] for s in sites}
        for fu in as_completed(futs):
            done += 1
            p = os.environ.get("WORKERQ_PROGRESS")
            if p:
                Path(p).write_text(f"{done / len(sites):.4f}")
            try:
                print(fu.result(), flush=True)
            except Exception:
                fails += 1
                print(f"{futs[fu]}: ERROR\n{traceback.format_exc()}", flush=True)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
