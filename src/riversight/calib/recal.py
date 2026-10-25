"""Weekly self-recalibration on the worker, shadow-first (W4, D-0014 W4-1).

    every cycle   log_features(): the reading's v1 block features + DINO tokens + matched gauge → S3
    weekly        refit(): base training set ∪ logged readings with a gauge within ±20 min → same v2 config,
                  same scene_v2.fit_bundle → live/recal/models/<cam>/ (+ local models/sites_recal/<cam>/)
    every cycle   the cycle scores the recalibrated bundle as a shadow (ShadowV2 on the same F, P)
    on approval   W2's RECALIBRATE (human-approved) makes the worker serve the recalibrated bundle

Evidence for doing this (results/v2/RECAL.md): weekly refit 0.240 vs fit-once 0.361 ft (v1; v2 0.165),
16/16 sites; share of readings above the calibrated range 7.9 % → 1.7 %.

S3 layout (the worker role may write live/* and read models/*):
  models/recal_base/<cam>.npz                 base set: what the served v2 bundle was trained on (t, h, F, P)
  live/recal/features/<cam>/<YYYYMMDD>/<HHMMSS>.npz   one logged reading
  live/recal/models/<cam>/{scene_model_v2.npz, meta_v2.json}   latest recalibrated bundle
  live/recal/residuals/<cam>/<YYYYMMDD>.jsonl  {t, raw, g} per reading with a matched gauge (cheap drift input)
  live/recal/drift/<cam>.json                 camera-vs-gauge residual drift over the last 7 days (W2's signal)

CLI (worker, weekly timer, or by hand):
  python -m riversight.calib.recal refit --s3 <bucket> --bundles models/sites_v2 --out models/sites_recal
  python -m riversight.calib.recal refit --local <dir> ...           (tests / local dry runs)
  python -m riversight.calib.recal drift --s3 <bucket> --bundles models/sites_v2   (cheap; hourly is fine)
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

FEAT_PREFIX = "live/recal/features"
MODEL_PREFIX = "live/recal/models"
DRIFT_PREFIX = "live/recal/drift"
RESID_PREFIX = "live/recal/residuals"
BASE_KEY = "models/recal_base/{cam}.npz"
MATCH = pd.Timedelta("20min")          # gauge within ±20 min of the frame (D-0010 §1 scoring rule)
EXCLUDE_FLAGS = ("VIEW_CHANGE", "LOW_QUALITY", "OUT_OF_RANGE")
MIN_NEW = 20                           # refit only with at least this many new usable readings
DRIFT_DAYS = 7


def _npz_bytes(**arrays) -> bytes:
    b = io.BytesIO()
    np.savez_compressed(b, **arrays)
    return b.getvalue()


def log_features(store, cam: str, t_frame, F16: np.ndarray, P16: np.ndarray, gauge_ft: float | None,
                 gauge_t, flags: list[str], raw_ft: float | None = None) -> str:
    """Persist one registered daylight reading for the weekly refit. F16 (3600, 5) and P16 (448, k) float16 are
    the arrays the cycle already computed; raw_ft is the served model's raw stage (for the drift signal)."""
    t = pd.Timestamp(t_frame).tz_convert("UTC")
    key = f"{FEAT_PREFIX}/{cam}/{t:%Y%m%d}/{t:%H%M%S}.npz"
    gt = pd.Timestamp(gauge_t).tz_convert("UTC").value if gauge_t is not None and gauge_ft is not None else -1
    store.put_bytes(key, _npz_bytes(t=np.int64(t.value), F=np.asarray(F16, np.float16), P=np.asarray(P16, np.float16),
                                    g=np.float64(np.nan if gauge_ft is None else gauge_ft), gt=np.int64(gt),
                                    raw=np.float64(np.nan if raw_ft is None else raw_ft),
                                    flags=np.array("|".join(flags or []))))
    fl = flags or []
    if raw_ft is not None and gauge_ft is not None and gt >= 0 and abs(gt - t.value) <= MATCH.value             and not any(f in fl for f in EXCLUDE_FLAGS):
        store.append_jsonl(f"{RESID_PREFIX}/{cam}/{t:%Y%m%d}.jsonl",
                           {"t": t.isoformat(), "raw": round(float(raw_ft), 4), "g": round(float(gauge_ft), 4)})
    return key


def residuals(store, cam: str, now=None, days: int = DRIFT_DAYS) -> dict:
    """{t, h, raw} from the residual day files of the last `days` days (no feature files are read)."""
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    rows = []
    for d in pd.date_range((now - pd.Timedelta(days=days)).floor("D"), now.floor("D"), freq="D"):
        b = store.get_bytes(f"{RESID_PREFIX}/{cam}/{d:%Y%m%d}.jsonl")
        for line in (b or b"").decode().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    if not rows:
        return {"t": pd.DatetimeIndex([], tz="UTC"), "h": np.zeros(0), "raw": np.zeros(0)}
    df = pd.DataFrame(rows)
    return {"t": pd.DatetimeIndex(pd.to_datetime(df["t"], utc=True)), "h": df["g"].to_numpy(float), "raw": df["raw"].to_numpy(float)}


def update_drift(store, cam: str, sigma_ft: float, now=None) -> dict:
    rep = {"cam_id": cam, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           **drift_report(residuals(store, cam, now), sigma_ft, now)}
    store.put_json(f"{DRIFT_PREFIX}/{cam}.json", rep)
    return rep


def load_logged(store, cam: str, since=None) -> dict:
    """Usable logged readings: gauge within ±20 min, no excluded flag. Returns t, h, F, P, raw (time-sorted)."""
    keys = sorted(k for k in store.list(f"{FEAT_PREFIX}/{cam}/") if k.endswith(".npz"))
    rows = []
    for k in keys:
        b = store.get_bytes(k)
        if b is None:
            continue
        z = np.load(io.BytesIO(b))
        t = pd.Timestamp(int(z["t"]), tz="UTC")
        if since is not None and t <= pd.Timestamp(since):
            continue
        fl = str(z["flags"]).split("|")
        g, gt = float(z["g"]), int(z["gt"])
        if not np.isfinite(g) or gt < 0 or abs(pd.Timestamp(gt, tz="UTC") - t) > MATCH or any(f in fl for f in EXCLUDE_FLAGS):
            continue
        rows.append((t, g, z["F"], z["P"], float(z["raw"])))
    rows.sort(key=lambda r: r[0])
    if not rows:
        return {"t": pd.DatetimeIndex([], tz="UTC"), "h": np.zeros(0), "F": None, "P": None, "raw": np.zeros(0), "n_keys": len(keys)}
    return {"t": pd.DatetimeIndex([r[0] for r in rows]), "h": np.array([r[1] for r in rows]),
            "F": np.stack([r[2] for r in rows]), "P": np.stack([r[3] for r in rows]),
            "raw": np.array([r[4] for r in rows]), "n_keys": len(keys)}


def drift_report(new: dict, sigma_ft: float, now=None) -> dict:
    """Served-model residual (raw − gauge) over the last DRIFT_DAYS. `drifting` when ≥ 20 readings and the
    median residual exceeds the site σ in magnitude; W2's RECALIBRATE rule reads this."""
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    m = (new["t"] >= now - pd.Timedelta(days=DRIFT_DAYS)) & np.isfinite(new["raw"])
    e = new["raw"][m] - new["h"][m]
    out = {"n": int(m.sum()), "window_days": DRIFT_DAYS, "sigma_ft": round(float(sigma_ft), 4) if np.isfinite(sigma_ft) else None}
    if m.sum():
        out.update(median_residual_ft=round(float(np.median(e)), 4), median_abs_residual_ft=round(float(np.median(np.abs(e))), 4))
    out["drifting"] = bool(m.sum() >= 20 and np.isfinite(sigma_ft) and abs(float(np.median(e))) > sigma_ft)
    return out


def _load_base(store, cam: str, cache: Path | None) -> dict | None:
    key = BASE_KEY.format(cam=cam)
    p = cache / f"{cam}.npz" if cache else None
    if p is not None and p.exists():
        b = p.read_bytes()
    else:
        b = store.get_bytes(key)
        if b is None:
            return None
        if p is not None:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b)
    z = np.load(io.BytesIO(b))
    return {"t": pd.DatetimeIndex(pd.to_datetime(z["t"], utc=True)), "h": z["h"], "F": z["F"], "P": z["P"]}


def refit_site(store, cam: str, bundles: Path, out: Path, cache: Path | None = None, min_new: int = MIN_NEW,
               now=None) -> dict:
    """Refit one site's served v2 configuration on base ∪ logged readings. Returns a status dict."""
    from riversight.calib.scene_v2 import fit_bundle, parse_config
    src = bundles / cam
    if not (src / "meta_v2.json").exists():
        return {"cam_id": cam, "status": "no served v2 bundle"}
    meta0 = json.loads((src / "meta_v2.json").read_text(encoding="utf-8"))
    a0 = np.load(src / "scene_model_v2.npz")
    new = load_logged(store, cam)
    drift = update_drift(store, cam, float(meta0.get("sigma_ft", float("nan"))), now)
    base = _load_base(store, cam, cache)
    if base is None:
        return {"cam_id": cam, "status": "no base set", "drift": drift}
    keep = new["t"] > base["t"][-1] if len(new["t"]) else np.zeros(0, bool)
    n_new = int(keep.sum())
    if n_new < min_new:
        return {"cam_id": cam, "status": f"skipped: {n_new} new usable readings (< {min_new})", "drift": drift}
    t = base["t"].append(new["t"][keep])
    h = np.concatenate([base["h"], new["h"][keep]])
    F = np.concatenate([base["F"], new["F"][keep]])
    P = np.concatenate([base["P"], new["P"][keep]])
    del base
    gc.collect()
    arr = fit_bundle(F, P, t, h, parse_config(meta0["config"]), float(meta0["lat"]), float(meta0["lon"]), float(a0["q"]))
    d = out / cam
    d.mkdir(parents=True, exist_ok=True)
    blob = _npz_bytes(**arr)
    (d / "scene_model_v2.npz").write_bytes(blob)
    meta = {**{k: meta0[k] for k in ("cam_id", "lat", "lon", "config", "dino_onnx_sha256", "pca_basis_sha256") if k in meta0},
            "sigma_ft": meta0.get("sigma_ft"), "n_train_frames": int(len(t)), "n_new_frames": n_new,
            "new_from": str(new["t"][keep][0]), "new_to": str(new["t"][keep][-1]),
            "stage_max_before_ft": round(float(h[:-n_new].max()), 3), "stage_max_after_ft": round(float(h.max()), 3),
            "parent_model_sha": meta0.get("model_sha"), "model_sha": hashlib.sha256(blob).hexdigest(),
            "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "label": "recalibrated v2, SHADOW until a human approves RECALIBRATE (D-0014)"}
    (d / "meta_v2.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    store.put_bytes(f"{MODEL_PREFIX}/{cam}/scene_model_v2.npz", blob)
    store.put_json(f"{MODEL_PREFIX}/{cam}/meta_v2.json", meta)
    del F, P, arr
    gc.collect()
    return {"cam_id": cam, "status": "refit", "n_new": n_new, "stage_max_before_ft": meta["stage_max_before_ft"],
            "stage_max_after_ft": meta["stage_max_after_ft"], "drift": drift}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m riversight.calib.recal")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refit")
    dr = sub.add_parser("drift")
    for sp in (r, dr):
        g = sp.add_mutually_exclusive_group(required=True)
        g.add_argument("--s3")
        g.add_argument("--local", type=Path)
        sp.add_argument("--bundles", type=Path, default=Path("models/sites_v2"))
        sp.add_argument("--only", nargs="*")
    r.add_argument("--out", type=Path, default=Path("models/sites_recal"))
    r.add_argument("--cache", type=Path, default=None, help="local cache for the base sets (downloaded once)")
    r.add_argument("--min-new", type=int, default=MIN_NEW)
    a = ap.parse_args(argv)
    from riversight.live.store import LocalStore, S3Store
    store = S3Store(a.s3) if a.s3 else LocalStore(a.local)
    cams = sorted(p.name for p in a.bundles.iterdir() if p.is_dir() and (not a.only or p.name in a.only))
    if a.cmd == "drift":
        for cam in cams:
            try:
                sigma = float(json.loads((a.bundles / cam / "meta_v2.json").read_text(encoding="utf-8")).get("sigma_ft"))
                print(json.dumps(update_drift(store, cam, sigma)), flush=True)
            except Exception as e:
                print(json.dumps({"cam_id": cam, "error": f"{type(e).__name__}: {e}"}), flush=True)
        return 0
    results = []
    for cam in cams:
        try:
            res = refit_site(store, cam, a.bundles, a.out, a.cache, a.min_new)
        except Exception as e:                       # one site never blocks the others
            res = {"cam_id": cam, "status": f"error: {type(e).__name__}: {e}"}
        results.append(res)
        print(json.dumps(res, default=str), flush=True)
    store.put_json(f"{MODEL_PREFIX}/_last_run.json", {"finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                                      "results": results})
    return 0 if not any(str(x["status"]).startswith("error") for x in results) else 1


if __name__ == "__main__":
    sys.exit(main())
