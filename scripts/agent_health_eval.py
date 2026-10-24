"""Evaluate the fleet camera-health checks (agent/health.py, D-0013 W2-3) on the cameras' history.

For every site with a history (20 frozen + onboarded), day by day over ~12 months:
  offline       a daylight gap > 6 h between consecutive NIMS uploads (sun >= 10 deg at the gap midpoint)
  view_changed  >= 50 % of the day's daylight frames fail registration to the main reference (>= 4 frames)
  ir_stuck_on   >= 50 % of frames with sun >= 10 deg are NIGHT-flagged, confirmed monochrome (chroma < 1) on up to 3
  lens          agent/health.lens_flags: vs the camera's own trailing 14-day baseline (3 sampled frames per day)

Agreement: view_changed days vs the independent day-level failure-run analysis of SLICE_01B
(`history/segments.csv`: runs of days with < 30 % registration success, >= 3 days long; unlinked runs only — a
linked run registers through the reference bank). Offline is counted, not scored
(the upload record is the ground truth). Lens and IR have no labels: the flagged days are written to a local contact
sheet (runs/agent_health_eval/, not committed: raw frames) for a by-eye spot check.

  workerq ... -- python scripts/agent_health_eval.py
Output: results/agent_eval/health_eval.json
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from riversight.agent.health import DAY_SUN_DEG, IR_CHROMA, IR_SHARE, OFFLINE_H, VIEW_SHARE, chroma, lens_flags  # noqa: E402
from riversight.live.quality import image_quality  # noqa: E402

DATA = ROOT / "data"
OUT = ROOT / "results" / "agent_eval" / "health_eval.json"
SHEETS = ROOT / "runs" / "agent_health_eval"


def sites() -> list[tuple[str, Path]]:
    out = []
    for root in (ROOT / "models" / "sites", ROOT / "models" / "onboard"):
        if root.exists():
            out += [(d.name, d) for d in sorted(root.iterdir()) if (d / "meta.json").exists()]
    return out


def _sun(lat: float, lon: float, ts: pd.DatetimeIndex) -> np.ndarray:
    """NOAA-style solar elevation (deg), vectorised; good to ~0.5 deg, plenty for a 10 deg daylight test."""
    t = ts.tz_convert("UTC")
    doy = t.dayofyear.to_numpy()
    hr = (t.hour + t.minute / 60).to_numpy()
    g = 2 * np.pi / 365 * (doy - 1 + (hr - 12) / 24)
    decl = 0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g) - 0.006758 * np.cos(2 * g) + 0.000907 * np.sin(2 * g)
    eqt = 229.18 * (0.000075 + 0.001868 * np.cos(g) - 0.032077 * np.sin(g) - 0.014615 * np.cos(2 * g) - 0.040849 * np.sin(2 * g))
    tst = hr * 60 + eqt + 4 * lon
    ha = np.radians(tst / 4 - 180)
    la = np.radians(lat)
    cz = np.sin(la) * np.sin(decl) + np.cos(la) * np.cos(decl) * np.cos(ha)
    return np.degrees(np.arcsin(np.clip(cz, -1, 1)))


def site_eval(cam: str, bdir: Path) -> dict:
    meta = json.loads((bdir / "meta.json").read_text(encoding="utf-8"))
    d = DATA / "derived" / cam / "history"
    f = pd.read_parquet(d / "frames.parquet").merge(
        pd.read_parquet(d / "registration.parquet")[["filename", "ok", "night_img"]], on="filename").sort_values("time")
    f["sun"] = _sun(meta["lat"], meta["lon"], pd.DatetimeIndex(f["time"]))
    f["day"] = f["time"].dt.strftime("%Y-%m-%d")
    out = {"cam_id": cam, "days": int(f["day"].nunique()), "offline_periods": 0, "view_changed_days": [], "ir_days": [],
           "lens_days": []}
    # offline: daylight gaps between uploads
    t = pd.DatetimeIndex(f["time"])
    gaps = (t[1:] - t[:-1]).total_seconds() / 3600
    mid = t[:-1] + (t[1:] - t[:-1]) / 2
    sun_mid = _sun(meta["lat"], meta["lon"], mid)
    out["offline_periods"] = int(np.sum((gaps > OFFLINE_H) & (sun_mid >= DAY_SUN_DEG)))
    out["offline_longest_h"] = round(float(gaps[sun_mid >= DAY_SUN_DEG].max()), 1) if np.any(sun_mid >= DAY_SUN_DEG) else 0.0
    day = f[f["sun"] >= DAY_SUN_DEG]
    lens_rows = []
    for dname, g in day.groupby("day"):
        if len(g) >= 4:
            if (~g["ok"].astype(bool)).mean() >= VIEW_SHARE:
                out["view_changed_days"].append(dname)
            if g["night_img"].astype(bool).mean() >= IR_SHARE:
                out["ir_candidate_days"] = out.get("ir_candidate_days", 0) + 1
                chs = []
                for p in g[g["night_img"].astype(bool)]["path"].iloc[:3]:
                    im = cv2.imread(str(ROOT / p))
                    if im is not None:
                        chs.append(chroma(im))
                if chs and float(np.median(chs)) < IR_CHROMA:
                    out["ir_days"].append(dname)
        pick = g.iloc[np.linspace(0, len(g) - 1, min(3, len(g))).astype(int)]
        qs = []
        for p in pick["path"]:
            img = cv2.imread(str(ROOT / p)) if not Path(p).is_absolute() else cv2.imread(p)
            if img is not None:
                qs.append(image_quality(img))
        if qs:
            lens_rows.append((dname, float(np.median([q["lap_var"] for q in qs])), float(np.median([q["fog_score"] for q in qs])),
                              pick["path"].iloc[len(pick) // 2]))
    out["lens_days"] = [f["day"] for f in lens_flags([r[:3] for r in lens_rows])]        # the live function
    out["_lens_examples"] = [r[3] for r in lens_rows if r[0] in set(out["lens_days"])][:6]
    out["_ir_examples"] = [g["path"].iloc[len(g) // 2] for dname, g in day.groupby("day") if dname in set(out["ir_days"])][:6]
    # agreement with the independent SLICE_01B failure-run segments
    seg_days = set()
    sp = d / "segments.csv"
    if sp.exists():
        for _, s in pd.read_csv(sp).iterrows():
            if bool(s["linked"]):
                continue          # a linked segment registers through the reference bank: not a view the camera lost
            seg_days |= {x.strftime("%Y-%m-%d") for x in pd.date_range(s["start"], s["end"])}
    vc = set(out["view_changed_days"])
    obs_days = set(day["day"])
    seg_obs = seg_days & obs_days
    out["segment_days"] = len(seg_obs)
    out["segment_days_flagged"] = len(seg_obs & vc)
    out["flagged_outside_segments"] = len(vc - seg_days)
    return out


def contact_sheet(paths: list[str], out: Path, title: str):
    tiles = []
    for p in paths[:12]:
        img = cv2.imread(str(ROOT / p))
        if img is None:
            continue
        img = cv2.resize(img, (320, 180), interpolation=cv2.INTER_AREA)
        cv2.putText(img, Path(p).stem[-20:], (4, 172), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1, cv2.LINE_AA)
        tiles.append(img)
    if not tiles:
        return
    while len(tiles) % 4:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]
    sheet = np.vstack(rows)
    cv2.putText(sheet, title, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), sheet)


def main():
    res, lens_ex, ir_ex = [], [], []
    S = sites()
    for i, (cam, bdir) in enumerate(S):
        try:
            r = site_eval(cam, bdir)
        except FileNotFoundError as e:
            r = {"cam_id": cam, "error": f"missing {Path(str(e)).name}"}
        lens_ex += [(cam, p) for p in r.pop("_lens_examples", [])]
        ir_ex += [(cam, p) for p in r.pop("_ir_examples", [])]
        res.append(r)
        p = os.environ.get("WORKERQ_PROGRESS")
        if p:
            Path(p).write_text(f"{(i + 1) / len(S):.4f}")
        print(cam[:50], {k: (len(v) if isinstance(v, list) else v) for k, v in r.items() if k != "cam_id"}, flush=True)
    ok = [r for r in res if "error" not in r]
    seg = sum(r["segment_days"] for r in ok)
    summ = {"sites": len(ok), "site_days": sum(r["days"] for r in ok),
            "offline_periods_gt6h_daylight": sum(r["offline_periods"] for r in ok),
            "sites_with_offline_periods": sum(r["offline_periods"] > 0 for r in ok),
            "view_changed_days": sum(len(r["view_changed_days"]) for r in ok),
            "segment_days_independent": seg, "segment_days_flagged": sum(r["segment_days_flagged"] for r in ok),
            "view_change_recall_vs_segments": round(sum(r["segment_days_flagged"] for r in ok) / seg, 3) if seg else None,
            "view_changed_days_outside_segments": sum(r["flagged_outside_segments"] for r in ok),
            "ir_candidate_days_saturation_test": sum(r.get("ir_candidate_days", 0) for r in ok),
            "ir_stuck_days_chroma_confirmed": sum(len(r["ir_days"]) for r in ok), "lens_days": sum(len(r["lens_days"]) for r in ok),
            "sites_with_lens_days": sum(len(r["lens_days"]) > 0 for r in ok)}
    OUT.write_text(json.dumps({"summary": summ, "per_site": res,
                               "note": "offline counted from the NIMS upload record; view change compared with the "
                                       "independent SLICE_01B failure-run segments; lens/IR have no labels (by-eye spot "
                                       "check on local contact sheets)"}, indent=1), encoding="utf-8")
    contact_sheet([p for _, p in lens_ex], SHEETS / "lens_flagged.jpg", "lens_degradation flagged days (sample)")
    contact_sheet([p for _, p in ir_ex], SHEETS / "ir_flagged.jpg", "ir_stuck_on flagged days (sample)")
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
