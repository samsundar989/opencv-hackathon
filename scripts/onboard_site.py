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

import numpy as np
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
    if not df.empty:                                     # camera type + batch (D-0013: % qualifying by type)
        from riversight.onboard.types import camera_type
        fl = {x["cam_id"]: x for x in yaml.safe_load(FLEET.read_text(encoding="utf-8"))["sites"]} if FLEET.exists() else {}
        df["camera_type"] = [camera_type(c, fl.get(c, {}).get("state"), fl.get(c, {}).get("lat")) for c in df["cam_id"]]
        df["batch"] = [fl.get(c, {}).get("batch", 1) for c in df["cam_id"]]
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
    cost(done)
    readme(df)
    if FLEET.exists():
        doc = yaml.safe_load(FLEET.read_text(encoding="utf-8"))
        el = set(live["cam_id"])
        tiers = dict(zip(df["cam_id"], df["tier"]))
        for s in doc["sites"]:
            s["live"] = s["cam_id"] in el
            s["tier"] = tiers.get(s["cam_id"])
        FLEET.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(json.dumps(summ, indent=2, default=str))


VCPU_USD_H = 0.0978 / 2       # m9g.large on-demand, us-east-2 (docs/status/W1.md), per vCPU-hour
HIVIS_GAUGED = 880             # gauged HIVIS cameras to cover (SPRINT_W5 A.5)


def cost(done: pd.DataFrame):
    """Measured cost to onboard one camera (medians over finished sites) and the projection to the gauged fleet.
    CPU stages run single-threaded per site, so their wall seconds are CPU-seconds (measured on the x86 dev box;
    the $ figure assumes the same CPU-seconds on Graviton, which W3's COOL benchmark can correct)."""
    if done.empty:
        return
    cpu_cols = [c for c in ("s_reference", "s_register_features", "s_cv", "s_export") if c in done]
    cpu_s = done[cpu_cols].fillna(0).sum(axis=1)
    mb = [sum(f.stat().st_size for f in (DATA / "raw" / "720" / c).glob("*.jpg")) / 1e6 for c in done["cam_id"]]
    per = {"sites_measured": int(len(done)),
           "nims_listing_calls_median": float(done["nims_calls"].median()),
           "usgs_iv_requests_per_site": round(1 / 8, 3),          # 8 gauges per legacy IV request in onboard_scan.py
           "frames_downloaded_median": float(done["downloads"].median()),
           "mb_downloaded_median": float(np.median(mb)),
           "fetch_wall_s_median": float(done["s_fetch"].median()) if "s_fetch" in done else None,
           "cpu_s_median": float(cpu_s.median()), "cpu_s_p90": float(cpu_s.quantile(0.9)),
           "usd_per_site_median": float(cpu_s.median() / 3600 * VCPU_USD_H),
           "cameras_per_cpu_hour": float(3600 * len(done) / cpu_s.sum()) if cpu_s.sum() else None}
    proj = {"cameras": HIVIS_GAUGED,
            "nims_listing_calls": per["nims_listing_calls_median"] * HIVIS_GAUGED,
            "gb_downloaded": per["mb_downloaded_median"] * HIVIS_GAUGED / 1000,
            "cpu_hours": per["cpu_s_median"] * HIVIS_GAUGED / 3600,
            "usd_compute": per["usd_per_site_median"] * HIVIS_GAUGED,
            "wall_hours_fetch_sequential": (per["fetch_wall_s_median"] or 0) * HIVIS_GAUGED / 3600,
            "wall_hours_cpu_on_16_vcpu": per["cpu_s_median"] * HIVIS_GAUGED / 3600 / 16}
    out = {"per_camera": per, "projection_all_gauged_hivis": proj, "price_basis": "m9g.large $0.0978/h on-demand (2 vCPU)",
           "note": "CPU-seconds measured on the x86 dev box (sam-mega-pc), single thread per site."}
    (pl.RES / "cost.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


def readme(df: pd.DataFrame):
    """results/onboarding/README.md from the per-site records, fewshot_summary.csv and cost.json (no typed numbers)."""
    f = lambda x, n=2: "–" if x is None or pd.isna(x) else f"{x:.{n}f}"  # noqa: E731
    done = df[df["status"] == "done"].copy()
    live = done[done["live_eligible"].fillna(False).astype(bool)]
    L = ["# Fleet onboarding (SPRINT W5, D-0010 §3)", "",
         f"Generated by `scripts/onboard_site.py --summarise`. **{pl.LABEL}.** Every site uses the frozen D-0007 setting "
         "with no per-site tuning; CV is the same forward-chaining monthly CV (7-day gap) on the 12 months to 2026-10-23; "
         "tiers follow the D-0007 rules (C if registration < 0.80 over the last 30 days, CV Spearman < 0.5, or "
         "< 90 calibration days). Only tier A/B sites are handed to W1 for serving.", "",
         f"- Sites attempted: **{len(df)}**; finished: **{len(done)}**; tier B: **{int((done['tier'] == 'B').sum())}**; "
         f"tier C: **{int((done['tier'] == 'C').sum())}**; errors: {int((df['status'] == 'error').sum())}.",
         f"- Tier-B sites: median CV MAE **{f(live['mae'].median())} ft**, median nMAE **{f(live['nmae'].median(), 3)}** "
         f"(the frozen 20-site D-0007 CV: 0.380 ft, nMAE 0.145). P1 met at {int(live['p1'].fillna(False).astype(bool).sum())}/{len(live)}.",
         f"- Camera beats the 24 h last-known gauge value (CV frames) at "
         f"**{int((live['mae'] < live['mae_p24']).sum())}/{len(live)}** tier-B sites. The camera is a gap-filler, "
         "not a replacement for a working gauge.", "",
         "| site | tier | CV MAE ft | nMAE | P1 | Spearman | 24 h last-known MAE | reg. last 30 d | why |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in done.sort_values(["tier", "nmae"]).itertuples():
        L.append(f"| {r.cam_id} | {r.tier} | {f(r.mae)} | {f(r.nmae, 3)} | {'yes' if r.p1 else 'no'} | {f(r.spearman)} | "
                 f"{f(r.mae_p24)} | {f(r.reg_rate_last30d)} | {r.tier_reason or ''} |")
    for r in df[df["status"] != "done"].itertuples():
        L.append(f"| {r.cam_id} | – | – | – | – | – | – | – | {r.status}: {r.error or ''} |")
    fs = pl.RES / "fewshot_summary.csv"
    if fs.exists():
        s = pd.read_csv(fs)
        L += ["", "## How long until a new camera is useful? (`fewshot.csv`)", "",
              f"Same last-2-month test set for every calibration length, {int(s['sites'].max())} sites (kill-test history + onboarded).", "",
              "| days of calibration | " + " | ".join(str(d) for d in s["days"]) + " |",
              "|---|" + "---|" * len(s),
              "| median MAE ft | " + " | ".join(f(x, 3) for x in s["median_mae"]) + " |",
              "| median nMAE | " + " | ".join(f(x, 3) for x in s["median_nmae"]) + " |",
              "| P1 sites | " + " | ".join(str(int(x)) for x in s["p1_sites"]) + " |"]
    cp = pl.RES / "cost.json"
    if cp.exists():
        c = json.loads(cp.read_text(encoding="utf-8"))
        pc, pj = c["per_camera"], c["projection_all_gauged_hivis"]
        if "camera_type" in done:
            g = done.groupby("camera_type").agg(n=("cam_id", "size"), b=("live_eligible", lambda x: int(x.fillna(False).astype(bool).sum())),
                                                 nmae=("nmae", "median"), mae=("mae", "median"))
            L += ["", "## Qualifying by camera type (type from the camera id, state and latitude: `riversight.onboard.types`)", "",
                  "| camera type | onboarded | tier B (served) | % qualifying | median CV nMAE | median CV MAE ft |", "|---|---|---|---|---|---|"]
            for t, r in g.iterrows():
                L.append(f"| {t} | {int(r.n)} | {int(r.b)} | {100 * r.b / r.n:.0f} % | {f(r.nmae, 3)} | {f(r.mae)} |")
        L += ["", "## Cost to onboard one camera (`cost.json`)", "",
              f"Medians over {pc['sites_measured']} finished sites: {pc['nims_listing_calls_median']:.0f} NIMS listing calls, "
              f"{pc['usgs_iv_requests_per_site']} USGS IV requests (8 gauges per request), {pc['mb_downloaded_median']:.0f} MB of "
              f"720-px frames, fetch {pc['fetch_wall_s_median']:.0f} s wall, **{pc['cpu_s_median'] / 60:.0f} CPU-minutes** "
              f"(p90 {pc['cpu_s_p90'] / 60:.0f}), **${pc['usd_per_site_median']:.3f}** at {c['price_basis']}.",
              f"Throughput: **{pc.get('cameras_per_cpu_hour') or 0:.2f} cameras per CPU-hour** (all finished sites).",
              f"Projected to all {pj['cameras']} gauged HIVIS cameras: {pj['cpu_hours']:.0f} CPU-hours "
              f"(**${pj['usd_compute']:.0f}** compute; {pj['wall_hours_cpu_on_16_vcpu']:.0f} h on 16 vCPU), "
              f"{pj['gb_downloaded']:.0f} GB of frames, {pj['nims_listing_calls']:.0f} NIMS calls "
              f"({pj['wall_hours_fetch_sequential']:.0f} h of polite sequential fetching). {c['note']}"]
    L += ["", "## Hand-off to W1", "",
          "- Bundles: `models/onboard/<cam_id>/` (INTERFACES §1 layout; `meta.json` has `onboarded: true` and the label).",
          "- Site list: `data/sites/fleet_v2.yaml`, where `live: true` marks the tier A/B sites (the D-0010 §3 rule; Q-0012 asks "
          "Cowork whether to serve all of them).",
          "- Prospective scoring (D-0010 §1) for these sites starts at each site's first live cycle, with the bundle's `model_sha` frozen then."]
    (pl.RES / "README.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cams", nargs="*")
    ap.add_argument("--batch", type=Path)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--skip", nargs="*", default=[])
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
        sites = [s for s in sites if s["cam_id"] not in a.skip]
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
                fe = pl.fetch(s, P, nims)
            except Exception as e:
                rec["status"], rec["error"] = "error", f"fetch: {e!r}"[:500]
                pl.save_record(s["cam_id"], rec)
                print(f"[{i}/{len(sites)}] {s['cam_id']}: fetch ERROR {e!r}"[:300], flush=True)
                continue
            if fe.get("nims_calls") or "fetch" not in rec:          # a cached rerun keeps the first run's measured cost
                rec["fetch"] = fe
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
