"""SPRINT W5 A.2: one-command onboarding of a HIVIS camera (frozen D-0007 setting, no per-site tuning).

  python scripts/onboard_site.py <cam_id> [<cam_id> ...]       sites must be in data/sites/fleet_v2.yaml or pool.csv
  python scripts/onboard_site.py --batch data/sites/fleet_v2.yaml --jobs 8
  python scripts/onboard_site.py --summarise                   results/onboarding/summary.{csv,json}; live flags

Fetch runs in the main process, one site at a time (NIMS listing paced, downloads ≤ 4 parallel); each fetched
site goes straight to a worker process for reference → register+features → CV → tier → export
(riversight.onboard.pipeline). Bundles land in models/onboard/<cam>/ for W1. Everything is cached, so a rerun
resumes. Heavy (CPU, ~1.5 GiB per worker): run through worker-q, e.g.

  workerq submit --project riversight --priority high --ram 14 --cpus 8 --node local \
    --describe "W5 onboarding batch" -- C:/Users/samsu/AppData/Local/Python/pythoncore-3.14-64/python.exe \
    scripts/onboard_site.py --batch data/sites/fleet_v2.yaml --jobs 8 --out C:/Users/samsu/Documents/opencv-hackathon/models/onboard
"""
from __future__ import annotations

import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from riversight.onboard import pipeline as pl  # noqa: E402

DATA = pl.DATA
FLEET = DATA / "sites" / "fleet_v2.yaml"


def _worker(site: dict, out: str, do_export: bool) -> dict:
    import cv2
    cv2.setNumThreads(1)
    os.environ.pop("WORKERQ_PROGRESS", None)
    os.chdir(ROOT)                                   # frames.parquet paths are repo-relative
    return pl.process(site, Path(out), do_export)


def sites_for(cams: list[str]) -> list[dict]:
    fleet = yaml.safe_load(FLEET.read_text(encoding="utf-8"))["sites"] if FLEET.exists() else []
    by = {s["cam_id"]: s for s in fleet}
    missing = [c for c in cams if c not in by]
    if missing:
        pool = pd.read_csv(pl.RES / "pool.csv", dtype={"nwis_id": str}).drop_duplicates("cam_id").set_index("cam_id")
        for c in missing:
            r = pool.loc[c]
            by[c] = {"cam_id": c, "nwis_id": str(r["nwis_id"]).zfill(8), "state": r["state"], "lat": float(r["lat"]),
                     "lng": float(r["lng"]), "name": r["name"], "live": False}
        # site_latlng() (sun-based night QA) reads data/sites/*.yaml, so ad-hoc sites join fleet_v2.yaml
        doc = yaml.safe_load(FLEET.read_text(encoding="utf-8")) if FLEET.exists() else {"sites": []}
        doc["sites"] = doc.get("sites", []) + [by[c] for c in missing]
        FLEET.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return [by[c] for c in cams]


def summarise():
    rows = []
    for p in sorted(pl.RES.glob("*.json")):
        if p.stem in ("summary", "cost") or p.stem.startswith("_"):
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        if "cam_id" not in r:
            continue
        cv, reg, fe, s = r.get("cv", {}), r.get("registration", {}), r.get("fetch", {}), r.get("seconds", {})
        rows.append({"cam_id": r["cam_id"], "status": r.get("status"), "tier": r.get("tier"), "live_eligible": r.get("live_eligible"),
                     "tier_reason": cv.get("tier_reason"), "n_oof": cv.get("n_oof"), "n_folds": cv.get("n_folds"),
                     "mae": cv.get("mae"), "median_ae": cv.get("median_ae"), "nmae": cv.get("nmae"), "p1": cv.get("p1"),
                     "within_025": cv.get("within_025"), "spearman": cv.get("cv_spearman"), "mae_p24": cv.get("mae_p24"),
                     "mae_const": cv.get("mae_const"), "gap_24h_lkv": cv.get("gap_24h_lkv"), "gap_24h_cam": cv.get("gap_24h_cam"),
                     "gap_7d_lkv": cv.get("gap_7d_lkv"), "gap_7d_cam": cv.get("gap_7d_cam"),
                     "sigma_ft": cv.get("sigma_ft"), "cal_days": cv.get("cal_days"), "cal_frames": cv.get("cal_frames"),
                     "calib_p5_p95_ft": cv.get("calib_p5_p95_ft"), "reg_rate_last30d": reg.get("reg_rate_last30d"),
                     "reg_rate_all": reg.get("reg_rate_all"), "view_change_runs": reg.get("view_change_runs"),
                     "listed": fe.get("listed"), "selected": fe.get("selected"), "nims_calls": fe.get("nims_calls"),
                     "downloads": fe.get("downloads"), **{f"s_{k}": v for k, v in s.items()}, "error": r.get("error")})
    df = pd.DataFrame(rows)
    if df.empty:
        print("no onboarding records yet")
        return
    df.to_csv(pl.RES / "summary.csv", index=False)
    done = df[df["status"] == "done"]
    live = df[df["live_eligible"].fillna(False).astype(bool)]
    summ = {"label": pl.LABEL, "sites_attempted": int(len(df)), "sites_done": int(len(done)),
            "tiers": done["tier"].value_counts().to_dict(), "live_eligible": int(len(live)),
            "cv_median_mae_ft_all_done": float(done["mae"].median()) if len(done) else None,
            "cv_median_mae_ft_live_eligible": float(live["mae"].median()) if len(live) else None,
            "cv_median_nmae_live_eligible": float(live["nmae"].median()) if len(live) else None,
            "p1_sites_done": int(done["p1"].fillna(False).astype(bool).sum()),
            "errors": df.loc[df["status"] == "error", ["cam_id", "error"]].to_dict("records")}
    (pl.RES / "summary.json").write_text(json.dumps(summ, indent=2, default=str), encoding="utf-8")
    if FLEET.exists():
        doc = yaml.safe_load(FLEET.read_text(encoding="utf-8"))
        el = set(live["cam_id"])
        tiers = dict(zip(df["cam_id"], df["tier"]))
        for s in doc["sites"]:
            s["live"] = s["cam_id"] in el
            s["tier"] = tiers.get(s["cam_id"])
        FLEET.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(json.dumps(summ, indent=2, default=str))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cams", nargs="*")
    ap.add_argument("--batch", type=Path)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--pace", type=float, default=2.4)
    ap.add_argument("--out", type=Path, default=ROOT / "models" / "onboard")
    ap.add_argument("--no-export", action="store_true")
    ap.add_argument("--summarise", action="store_true")
    a = ap.parse_args()
    if a.summarise:
        return summarise()
    if a.batch:
        sites = yaml.safe_load(a.batch.read_text(encoding="utf-8"))["sites"]
        if a.only:
            sites = [s for s in sites if s["cam_id"] in a.only]
    else:
        sites = sites_for(a.cams)
    sites = sites[: a.limit] if a.limit else sites
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    import fetch_history as fh
    from riversight.data.nims import NimsClient
    nims = NimsClient(api_key=os.getenv("USGS_API_KEY"))
    P = fh.Paced(nims, a.pace, None)
    os.chdir(ROOT)
    n_done, futs = 0, {}
    with ProcessPoolExecutor(a.jobs) as ex:
        for i, s in enumerate(sites, 1):
            rec = pl.load_record(s["cam_id"])
            if rec.get("status") == "done":
                print(f"[{i}/{len(sites)}] {s['cam_id']}: already onboarded (tier {rec.get('tier')})", flush=True)
                continue
            t0 = time.time()
            try:
                rec["fetch"] = pl.fetch(s, P, nims)
            except Exception as e:
                rec["status"], rec["error"] = "error", f"fetch: {e!r}"[:500]
                pl.save_record(s["cam_id"], rec)
                print(f"[{i}/{len(sites)}] {s['cam_id']}: fetch ERROR {e!r}"[:300], flush=True)
                continue
            rec.setdefault("seconds", {})["fetch"] = round(time.time() - t0, 1)
            rec.update(nwis_id=s["nwis_id"], state=s.get("state"), name=s.get("name"), status="fetched")
            pl.save_record(s["cam_id"], rec)
            print(f"[{i}/{len(sites)}] {s['cam_id']}: fetched {rec['fetch']} ({rec['seconds']['fetch']:.0f}s)", flush=True)
            futs[ex.submit(_worker, s, str(a.out), not a.no_export)] = s["cam_id"]
        for fu in as_completed(futs):
            n_done += 1
            p = os.environ.get("WORKERQ_PROGRESS")
            if p:
                Path(p).write_text(f"{n_done / max(len(futs), 1):.4f}")
            try:
                r = fu.result()
                cv = r.get("cv", {})
                print(f"{futs[fu]}: {r.get('status')} tier {r.get('tier')} MAE {cv.get('mae')} nMAE {cv.get('nmae')} "
                      f"rho {cv.get('cv_spearman')} reg30 {r.get('registration', {}).get('reg_rate_last30d')} "
                      f"{r.get('seconds')} {r.get('error', '')}", flush=True)
            except Exception as e:
                print(f"{futs[fu]}: worker ERROR {e!r}", flush=True)
    summarise()


if __name__ == "__main__":
    main()
