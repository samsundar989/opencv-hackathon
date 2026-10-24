"""One-site onboarding, built from the existing SLICE_01B / W1 pieces with the onboarding window swapped in:

  fetch      scripts/fetch_history.py listing + selection (daylight every 2 h, hourly on event days), 720-px
             frames (≤ 4 parallel, cached); stage from the cached 12-month IV scan (data/raw/iv_12m).
  reference  killtest.choose_reference over the last 45 days (the view that goes live), recorded as a one-row
             registration_cascade.parquet so riversight.history and export_site_models find it.
  register   riversight.history.register_history (ORB → ALIKED+LightGlue → chain, USAC_MAGSAC, piecewise
             references on view changes) + scene features (scripts/scene_features.py).
  cv         frozen D-0007 setting, forward-chaining monthly CV (riversight.onboard.cv).
  tier       D-0007 rules (scene_score.tier_of): C if registration < 0.80 over the last 30 days, CV Spearman
             < 0.5 or < 90 calibration days; otherwise B (tier A is reserved for the two named sites).
  export     scripts/export_site_models.export_site → models/onboard/<cam>/ (handed to W1; only A/B go live).

Every stage is cached on disk, so a preempted or failed run resumes. results/onboarding/<cam>.json records
coverage, CV metrics, tier and wall-clock seconds per stage.
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from riversight.onboard import W_END, W_START

ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))
RES = Path(os.environ.get("RIVERSIGHT_RESULTS", ROOT / "results")) / "onboarding"   # absolute when run from a worker-q snapshot
LABEL = "onboarded Oct 24-25, not part of the frozen test"


def _scripts():
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))


def _fh():
    _scripts()
    import fetch_history as fh
    fh.H_START, fh.H_END, fh.PROBE_FROM = W_START, W_END, W_START     # no pre-window probes
    return fh


def stage_from_scan(site: dict, d: Path) -> pd.DataFrame:
    sp = d / "stage.parquet"
    if sp.exists():
        return pd.read_parquet(sp)
    src = DATA / "raw" / "iv_12m" / f"{str(site['nwis_id']).zfill(8)}.parquet"
    if src.exists():
        s = pd.read_parquet(src).dropna(subset=["value"])[["time", "value"]].assign(source="nwis_iv_legacy")
    else:
        from riversight.data.nwis import legacy_iv_multi
        s = legacy_iv_multi([str(site["nwis_id"]).zfill(8)], W_START, W_END).get(
            str(site["nwis_id"]).zfill(8), pd.DataFrame(columns=["time", "value"])).assign(source="nwis_iv_legacy")
    d.mkdir(parents=True, exist_ok=True)
    s.to_parquet(sp, index=False)
    return s


def fetch(site: dict, paced, nims, workers: int = 4) -> dict:
    """Listing + selection + download + frames.parquet. `paced` is a fetch_history.Paced (one per process)."""
    from riversight.data.join import frames_table, join_frames_to_stage
    fh = _fh()
    cam = site["cam_id"]
    d = DATA / "derived" / cam / "history"
    if (d / "frames.parquet").exists():
        j = pd.read_parquet(d / "frames.parquet")
        return {"listed": len((d / "list.txt").read_text().splitlines()) if (d / "list.txt").exists() else None,
                "selected": len(j), "nims_calls": 0, "downloads": 0, "download_errors": 0}
    n0 = paced.n
    files, _ = fh.listing(paced, cam, d)
    st = stage_from_scan(site, d)
    sel = fh.select(frames_table(files), st, float(site["lat"]), float(site["lng"]))
    raw = DATA / "raw"
    jobs = [f for f in sel["filename"] if not (raw / "720" / cam / f).exists()] if len(sel) else []
    errs = 0
    with ThreadPoolExecutor(min(workers, 4)) as ex:
        for fu in as_completed([ex.submit(nims.download, cam, f, raw, "720") for f in jobs]):
            try:
                fu.result()
            except Exception:
                errs += 1
    if len(sel):
        j = join_frames_to_stage(sel[["filename", "cam_id", "time"]], st)
        j = j.merge(sel[["filename", "event_day"]], on="filename")
        j = j[[(raw / "720" / cam / f).exists() for f in j["filename"]]]
        j["path"] = [str(Path("data") / "raw" / "720" / cam / f) for f in j["filename"]]
    else:
        j = pd.DataFrame(columns=["filename", "cam_id", "time", "stage_ft", "event_day", "path"])
    j.to_parquet(d / "frames.parquet", index=False)
    return {"listed": len(files), "selected": int(len(sel)), "nims_calls": paced.n - n0, "downloads": len(jobs),
            "download_errors": errs}


def choose_reference(cam: str, days: int = 45) -> str:
    """Sharpest daylight frame near the median stage of the last `days` days."""
    from riversight.killtest import Cfg, choose_reference as pick
    out = DATA / "derived" / cam / "registration_cascade.parquet"
    if out.exists():
        return pd.read_parquet(out)["ref"].iloc[0]
    f = pd.read_parquet(DATA / "derived" / cam / "history" / "frames.parquet").dropna(subset=["stage_ft"])
    if not len(f):
        raise RuntimeError("no frames with gauge stage in the window")
    # the last `days` days that have gauge stage (a gauge dark at the window end must not block onboarding)
    end = min(pd.Timestamp(W_END), f["time"].max() + pd.Timedelta("1s"))
    f = f[f["time"] >= end - pd.Timedelta(days=days)].reset_index(drop=True)
    if len(f) < 10:
        raise RuntimeError(f"only {len(f)} frames with stage in the {days} days before {end:%Y-%m-%d}")
    f["window"] = "fit"
    f["path"] = [str(ROOT / p) for p in f["path"]]
    i, _ = pick(f, Cfg())
    name = f.loc[i, "filename"]
    pd.DataFrame({"ref": [name], "filename": [name], "source": ["onboard reference (last 45 days)"]}).to_parquet(out)
    return name


def register(cam: str) -> dict:
    _scripts()
    import cv2
    cv2.setNumThreads(1)
    import scene_features
    from riversight.history import register_history
    reg = register_history(DATA, cam)
    frames = pd.read_parquet(DATA / "derived" / cam / "history" / "frames.parquet")[["filename", "time"]]
    r = reg.merge(frames, on="filename")
    day = r[~r["night"].astype(bool)]
    recent = day[day["time"] >= pd.Timestamp(W_END) - pd.Timedelta(days=30)]
    scene_features.run(cam, "history", "all")
    seg = pd.read_csv(DATA / "derived" / cam / "history" / "segments.csv")
    return {"frames": int(len(r)), "daylight": int(len(day)), "reg_rate_all": float(day["ok"].mean()) if len(day) else np.nan,
            "reg_rate_last30d": float(recent["ok"].mean()) if len(recent) else np.nan, "n_daylight_last30d": int(len(recent)),
            "view_change_runs": int(len(seg)), "view_change_linked": int(seg["linked"].sum()) if len(seg) else 0}


def cv_and_tier(cam: str, reg_rate: float, cfg: dict) -> dict:
    from riversight.eval import protocol_v2 as pv
    from riversight.onboard.cv import frozen_cv
    _scripts()
    from scene_score import tier_of
    r = frozen_cv(DATA, cam, pd.Timestamp(W_END))
    if r is None:
        return {"tier": "C", "tier_reason": "too little data for forward-chaining CV", "n_oof": 0}
    ok = np.isfinite(r["oof"])
    t, h, oof = r["t"][ok], r["h"][ok], r["oof"][ok]
    rho = float(pd.Series(oof).corr(pd.Series(h), method="spearman")) if ok.sum() > 2 else float("nan")
    cal_days = float((r["t"][-1] - r["t"][0]).days)
    tier = tier_of(cam, cfg, reg_rate if np.isfinite(reg_rate) else 0.0, rho, cal_days)
    m = pv.site_metrics(t, oof, h, r["g"], r["h"], reg_rate, tier)
    why = [w for w, bad in (("registration < 0.80 (last 30 d)", not (reg_rate >= cfg["tier_c_reg_rate"])),
                            ("CV Spearman < 0.5", not (rho >= cfg["tier_c_cv_spearman"])),
                            ("< 90 calibration days", cal_days < cfg["tier_c_min_days"])) if bad]
    sig = float(np.std(oof - h)) if ok.sum() > 5 else float("nan")
    return {**{k: (float(v) if isinstance(v, (np.floating, float)) else v) for k, v in m.items()},
            "median_ae": float(np.median(np.abs(oof - h))), "within_025": float(np.mean(np.abs(oof - h) <= 0.25)),
            "cv_spearman": rho, "sigma_ft": sig, "n_oof": int(ok.sum()), "n_folds": int(r["n_folds"]),
            "cal_frames": int(len(r["t"])), "cal_days": cal_days, "tier_reason": "; ".join(why) or "meets tier B"}


def export(site: dict, tier: str, cfg: dict, out_root: Path) -> dict:
    import hashlib
    _scripts()
    import export_site_models as esm
    from riversight.onboard.cv import FROZEN
    sha = hashlib.sha256(FROZEN.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    out_root.mkdir(parents=True, exist_ok=True)
    msg = esm.export_site(site["cam_id"], site, cfg, sha, {site["cam_id"]: tier}, out_root, cut=W_END.strftime("%Y-%m-%d"))
    meta_p = out_root / site["cam_id"] / "meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    meta["label"] = f"live model ({LABEL}); trained on the 12 months before {W_END.date()}"
    meta["onboarded"] = True
    meta_p.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"bundle": str(Path("models") / "onboard" / site["cam_id"]), "model_sha": meta["model_sha"], "export_msg": msg}


def process(site: dict, out_root: Path, do_export: bool = True) -> dict:
    """Everything after fetch (CPU): reference → register+features → CV → tier → export. Updates the site JSON."""
    from riversight.onboard.cv import frozen_cfg
    cam = site["cam_id"]
    rec = load_record(cam)
    rec.setdefault("seconds", {})
    cfg = frozen_cfg()
    try:
        t0 = time.time()
        rec["reference"] = choose_reference(cam)
        rec["seconds"]["reference"] = round(time.time() - t0, 1)
        t0 = time.time()
        rec["registration"] = register(cam)
        rec["seconds"]["register_features"] = round(time.time() - t0, 1)
        t0 = time.time()
        rec["cv"] = cv_and_tier(cam, rec["registration"]["reg_rate_last30d"], cfg)
        rec["tier"] = rec["cv"]["tier"]
        rec["seconds"]["cv"] = round(time.time() - t0, 1)
        if do_export and rec["cv"].get("n_oof", 0) > 0:
            t0 = time.time()
            rec["export"] = export(site, rec["tier"], cfg, out_root)
            rec["seconds"]["export"] = round(time.time() - t0, 1)
        rec["status"] = "done"
        rec.pop("error", None)
    except Exception as e:                         # recorded, never silently dropped
        import traceback
        rec["status"], rec["error"] = "error", f"{e!r}"[:500]
        rec["traceback"] = traceback.format_exc()[-2000:]
    rec["live_eligible"] = rec.get("tier") in ("A", "B") and "export" in rec
    save_record(cam, rec)
    return rec


def load_record(cam: str) -> dict:
    p = RES / f"{cam}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"cam_id": cam, "label": LABEL}


def save_record(cam: str, rec: dict):
    RES.mkdir(parents=True, exist_ok=True)

    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        if isinstance(o, (np.floating, float)):
            return None if not np.isfinite(o) else round(float(o), 4)
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, np.bool_):
            return bool(o)
        return o
    (RES / f"{cam}.json").write_text(json.dumps(clean(rec), indent=2, default=str), encoding="utf-8")
