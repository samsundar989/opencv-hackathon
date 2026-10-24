"""SPRINT W5 A.1: rank onboarding candidates and write data/sites/fleet_v2.yaml.

Eligible (from results/onboarding/pool.csv, written by scripts/onboard_scan.py):
  visible camera with an nwisId gauge, an image in the last 48 h, created ≥ 120 days before the window end,
  00065 in ≥ 60 % of the 15-min slots of the 12-month window, not one of the 20 kill-test sites, not rejected in
  SLICE_01 by eye.
Shortlist = top `--shortlist` by stage swing (p95 − p5). For each shortlisted camera (cached under
data/derived/<cam>/onboard_probe/):
  * archive coverage: one 1-day NIMS listing every 30 days across the window (13 calls, paced);
  * daylight share and registration feasibility: 10 frames near local noon from the probe days, ORB+USAC_MAGSAC
    registered to the most recent one (killtest Cfg; ALIKED only if ORB fails) → median inliers, success rate.
Score = coverage × daylight × feasibility × min(swing / 2 ft, 1). Final pick: best `--n` with ≤ `--per-state`
per state; the sprint's named Texas flash-flood sites are taken first whenever they are eligible.

  python scripts/onboard_pool.py --shortlist 90 --n 40
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from riversight.data.join import frames_table  # noqa: E402
from riversight.data.nims import NimsClient  # noqa: E402
from riversight.onboard import W_END, W_START  # noqa: E402

DATA = Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))
RES = Path(os.environ.get("RIVERSIGHT_RESULTS", ROOT / "results")) / "onboarding"   # absolute when run from a worker-q snapshot
NAMED = ("Guadalupe_R", "Guadalupe_Rv_at_Comfort", "Blanco_R", "San_Antonio_R")
PROBE_EVERY_D = 30


def eligible(pool: pd.DataFrame) -> pd.DataFrame:
    slots = (W_END - W_START).total_seconds() / 900
    p = pool[(~pool["hidden"].astype(bool)) & pool["active_48h"].astype(bool) & (pool["age_days"] >= 120)
             & (pool["iv_n"] >= 0.6 * slots) & ~pool["in_kill_test"].astype(bool) & ~pool["rejected_slice01"].astype(bool)]
    return p.drop_duplicates("cam_id")


def probe(P, nims: NimsClient, cam: str, lat: float, lng: float) -> dict:
    import cv2
    from riversight.killtest import Cfg, is_night, make_registrar, sun_elevation_deg
    d = DATA / "derived" / cam / "onboard_probe"
    d.mkdir(parents=True, exist_ok=True)
    lp = d / "probe_list.csv"
    if lp.exists():
        pr = pd.read_csv(lp)
    else:
        rows, t = [], W_START + timedelta(days=PROBE_EVERY_D // 2)
        while t < W_END:
            for f in P.list(cam, t, t + timedelta(days=1)):
                rows.append({"day": t.date().isoformat(), "filename": f})
            rows.append({"day": t.date().isoformat(), "filename": ""})          # marks the day as probed
            t += timedelta(days=PROBE_EVERY_D)
        pr = pd.DataFrame(rows)
        pr.to_csv(lp, index=False)
    days = pr["day"].nunique()
    files = [f for f in pr["filename"].dropna() if f]
    cov = pr[pr["filename"].fillna("") != ""]["day"].nunique() / max(days, 1)
    out = {"probe_days": int(days), "probe_days_with_frames": int(pr[pr["filename"].fillna("") != ""]["day"].nunique()),
           "coverage": float(cov), "frames_per_day": len(files) / max(days, 1)}
    if not files:
        return {**out, "daylight": 0.0, "feas_ok": 0.0, "feas_inliers": 0}
    ft = frames_table(files)
    ft["sun"] = sun_elevation_deg(lat, lng, ft["time"])
    out["sun_up_share"] = float((ft["sun"] >= 3).mean())
    ft["day"] = ft["time"].dt.floor("D")
    noon = ft[ft["sun"] >= 15].sort_values("sun", ascending=False).drop_duplicates("day").sort_values("time")
    pick = noon.iloc[np.linspace(0, len(noon) - 1, min(10, len(noon))).astype(int)] if len(noon) else noon
    imgs = []
    for f in pick["filename"][::-1]:                                   # newest first; it is the reference
        try:
            imgs.append(cv2.imread(str(nims.download(cam, f, DATA / "raw", "720"))))
        except Exception:
            pass
    imgs = [im for im in imgs if im is not None]
    cfg = Cfg()
    day = [im for im in imgs if not is_night(im, cfg)]
    out["daylight"] = len(day) / max(len(imgs), 1)
    if len(day) < 3:
        return {**out, "feas_ok": 0.0, "feas_inliers": 0}
    ref = day[0]
    orb, ali = make_registrar(cfg, "orb"), None
    orb.set_reference(ref)
    ok, inl = [], []
    for im in day[1:]:
        if im.shape[:2] != ref.shape[:2]:
            ok.append(False); inl.append(0); continue
        r = orb.register(im)
        if not r.ok:
            if ali is None:
                ali = make_registrar(cfg, "aliked")
                ali.set_reference(ref)
            r = ali.register(im)
        ok.append(bool(r.ok)); inl.append(int(r.n_inliers))
    return {**out, "feas_ok": float(np.mean(ok)), "feas_inliers": int(np.median(inl)), "ref_shape": f"{ref.shape[0]}x{ref.shape[1]}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shortlist", type=int, default=90)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--per-state", type=int, default=6)
    ap.add_argument("--pace", type=float, default=1.5)
    a = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    import fetch_history as fh
    nims = NimsClient(api_key=os.getenv("USGS_API_KEY"))
    P = fh.Paced(nims, a.pace, None)
    pool = pd.read_csv(RES / "pool.csv", dtype={"nwis_id": str})
    el = eligible(pool).sort_values("iv_swing_ft", ascending=False)
    named = el[el["cam_id"].str.contains("|".join(NAMED))]
    short = pd.concat([named, el.head(a.shortlist)]).drop_duplicates("cam_id")
    print(f"{len(pool)} gauged cameras → {len(el)} eligible → shortlist {len(short)} ({len(named)} named TX)", flush=True)
    rows = []
    for k, r in enumerate(short.itertuples(), 1):
        t0 = time.time()
        try:
            pr = probe(P, nims, r.cam_id, r.lat, r.lng)
        except Exception as e:
            pr = {"probe_error": repr(e)[:200], "coverage": 0.0, "daylight": 0.0, "feas_ok": 0.0}
        rows.append({"cam_id": r.cam_id, **pr})
        print(f"[{k}/{len(short)}] {r.cam_id}: cov {pr.get('coverage', 0):.2f} day {pr.get('daylight', 0):.2f} "
              f"feas {pr.get('feas_ok', 0):.2f}/{pr.get('feas_inliers', 0)} ({time.time() - t0:.0f}s)", flush=True)
        p = os.environ.get("WORKERQ_PROGRESS")
        if p:
            Path(p).write_text(f"{k / len(short):.4f}")
    sc = short.merge(pd.DataFrame(rows), on="cam_id")
    sc["named_tx"] = sc["cam_id"].str.contains("|".join(NAMED))
    sc["score"] = (sc["coverage"].fillna(0) * sc["daylight"].fillna(0) * sc["feas_ok"].fillna(0)
                   * np.minimum(sc["iv_swing_ft"] / 2.0, 1.0))
    sc = sc.sort_values(["named_tx", "score"], ascending=False)
    picked, per = [], {}
    for r in sc.itertuples():
        if r.score <= 0 or r.coverage < 0.5 or r.feas_ok < 0.5:
            continue
        if per.get(r.state, 0) >= a.per_state and not r.named_tx:
            continue
        picked.append(r.cam_id)
        per[r.state] = per.get(r.state, 0) + 1
        if len(picked) >= a.n:
            break
    sc["picked"] = sc["cam_id"].isin(picked)
    sc.round(4).to_csv(RES / "candidates_ranked.csv", index=False)
    doc = {"description": "W5 fleet expansion (D-0010 §3): onboarded with the frozen D-0007 setting, no per-site tuning. "
                          "'live: true' only for tier A/B after forward-chaining CV (set by scripts/onboard_site.py --summarise). "
                          "Onboarded Oct 24-25, not part of the frozen test.",
           "window": {"start": W_START.isoformat(), "end": W_END.isoformat()},
           "selection": "scripts/onboard_pool.py → results/onboarding/candidates_ranked.csv",
           "sites": [{"cam_id": r.cam_id, "nwis_id": str(r.nwis_id).zfill(8), "state": r.state, "lat": float(r.lat),
                      "lng": float(r.lng), "name": r.name, "swing_ft": round(float(r.iv_swing_ft), 3),
                      "score": round(float(r.score), 4), "live": False}
                     for r in sc[sc["picked"]].itertuples()]}
    (DATA / "sites" / "fleet_v2.yaml").write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"picked {len(picked)}: {per}")


if __name__ == "__main__":
    main()
