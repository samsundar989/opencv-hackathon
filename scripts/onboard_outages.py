"""SPRINT W5 Part B: real gauge outages at HIVIS camera sites, and the camera bridging them.

  --catalog   results/real_outages/catalog.csv: every outage ≥ 6 h in the 12-month IV scan (scripts/onboard_scan.py)
              at every gauged camera, overlapping gap / estimated ('e') / equipment-qualified runs merged into one
              outage per site, with the number of daylight camera frames inside it (cached NIMS listings for
              calibrated sites; otherwise one paced 1-day-granular listing per outage, ≤ --max-calls).
  --score     results/real_outages/scored.csv for outages at calibrated sites (the 20 kill-test sites + onboarded
              sites) that have ≥ 3 registered daylight frames with features inside the outage:
                * model = frozen D-0007 setting refit on that site's calibration frames **excluding the outage ± 7 days**
                  (variant "excl7d"), and a stricter **past-only** refit on frames before outage start − 7 days ("causal");
                * truth: estimated outages → USGS's later backfill at each frame time (dense); hard gaps → the first
                  reading after the gauge returned, compared with the camera's last reading in the gap's final 6 h;
                * baseline: last-known value (the reading just before the outage).
              Outages overlapping the frozen test days (Oct 4–14, read once) are excluded at the 20 kill-test sites.
  --readme    results/real_outages/README.md from the two CSVs.
"""
from __future__ import annotations

import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")

import argparse
import json
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
from riversight.killtest import sun_elevation_deg  # noqa: E402
from riversight.onboard import W_END, W_START  # noqa: E402

DATA = Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))
OUT = Path(os.environ.get("RIVERSIGHT_RESULTS", ROOT / "results")) / "real_outages"
TEST_DAYS = (pd.Timestamp("2026-10-04", tz="UTC"), pd.Timestamp("2026-10-14", tz="UTC"))
KILL_CUT = pd.Timestamp("2026-10-03", tz="UTC")
PAD = pd.Timedelta("7D")


def kill_sites() -> dict:
    return {s["cam_id"]: s for s in yaml.safe_load((DATA / "sites" / "kill_test.yaml").read_text(encoding="utf-8"))["sites"]}


def onboarded_sites() -> dict:
    p = DATA / "sites" / "fleet_v2.yaml"
    out = {}
    if p.exists():
        for s in yaml.safe_load(p.read_text(encoding="utf-8"))["sites"]:
            rec = OUT.parent / "onboarding" / f"{s['cam_id']}.json"
            if rec.exists() and json.loads(rec.read_text(encoding="utf-8")).get("status") == "done":
                out[s["cam_id"]] = s
    return out


def merge_events(cat: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (cam, nid), g in cat.sort_values("start").groupby(["cam_id", "nwis_id"]):
        cur = None
        for e in g.itertuples():
            if cur and e.start <= cur["end"]:
                cur["end"] = max(cur["end"], e.end)
                cur["kinds"].add(e.kind)
                cur["codes"] |= set(str(e.codes).split("|")) - {"", "nan"}
                if not np.isfinite(cur["v_before"]):
                    cur["v_before"] = e.v_before
                cur["v_after"] = e.v_after if e.end >= cur["end"] else cur["v_after"]
            else:
                if cur:
                    rows.append(cur)
                cur = {"cam_id": cam, "nwis_id": nid, "state": e.state, "start": e.start, "end": e.end,
                       "kinds": {e.kind}, "codes": set(str(e.codes).split("|")) - {"", "nan"},
                       "v_before": e.v_before, "v_after": e.v_after}
        if cur:
            rows.append(cur)
    df = pd.DataFrame(rows)
    df["hours"] = (df["end"] - df["start"]).dt.total_seconds() / 3600
    df["kinds"] = df["kinds"].map(lambda s: "|".join(sorted(s)))
    df["codes"] = df["codes"].map(lambda s: "|".join(sorted(s)))
    df["truth"] = np.where(df["kinds"].str.contains("estimated"), "usgs_estimated_backfill", "after_return_only")
    return df


def cached_listing(cam: str) -> list[str] | None:
    files = []
    for p in (DATA / "derived" / cam / "history" / "list.txt", DATA / "derived" / cam / "list.txt",
              DATA / "derived" / cam / "list_30d.txt"):
        if p.exists():
            files += [x for x in p.read_text().splitlines() if x]
    return sorted(set(files)) if files else None


def catalog(max_calls: int, pace: float):
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    import fetch_history as fh
    from riversight.data.nims import NimsClient
    raw = pd.read_csv(OUT / "catalog_gauges.csv", dtype={"nwis_id": str}, parse_dates=["start", "end"])
    pool = pd.read_csv(OUT.parent / "onboarding" / "pool.csv", dtype={"nwis_id": str}).drop_duplicates("cam_id").set_index("cam_id")
    ev = merge_events(raw)
    calibrated = set(kill_sites()) | set(onboarded_sites())
    nims = NimsClient(api_key=os.getenv("USGS_API_KEY"))
    P = fh.Paced(nims, pace, None)
    cache_dir = DATA / "raw" / "onboard" / "outage_lists"
    cache_dir.mkdir(parents=True, exist_ok=True)
    ev["calibrated_site"] = ev["cam_id"].isin(calibrated)
    # calibrated sites first, then the rest by duration (longest outages matter most), within the call budget
    ev = ev.sort_values(["calibrated_site", "hours"], ascending=[False, False]).reset_index(drop=True)
    n_day, n_all, src, calls = [], [], [], 0
    for e in ev.itertuples():
        lat, lng = pool.loc[e.cam_id, "lat"], pool.loc[e.cam_id, "lng"]
        files, how = None, ""
        lst = cached_listing(e.cam_id)
        if lst is not None:
            ft = frames_table(lst)
            if len(ft) and ft["time"].min() <= e.start and ft["time"].max() >= e.end:
                files, how = lst, "cached_listing"
        if files is None:
            cp = cache_dir / f"{e.cam_id}__{e.start:%Y%m%dT%H%M}.txt"
            if cp.exists():
                files, how = [x for x in cp.read_text().splitlines() if x], "listing"
            elif calls < max_calls:
                files = P.list(e.cam_id, e.start.to_pydatetime(), e.end.to_pydatetime())
                cp.write_text("\n".join(files))
                calls += 1
                how = "listing"
        if files is None:
            n_day.append(np.nan); n_all.append(np.nan); src.append("not_checked (call budget)")
            continue
        ft = frames_table(files)
        ft = ft[(ft["time"] > e.start) & (ft["time"] < e.end)] if len(ft) else ft
        sun = sun_elevation_deg(lat, lng, ft["time"]) if len(ft) else np.array([])
        n_all.append(len(ft)); n_day.append(int((sun >= 3).sum())); src.append(how)
        if calls and calls % 100 == 0:
            print(f"  {calls} listing calls", flush=True)
    ev["camera_frames"] = n_all
    ev["camera_daylight_frames"] = n_day
    ev["frames_source"] = src
    ev["in_frozen_test_days"] = ev["cam_id"].isin(kill_sites()) & (ev["end"] > TEST_DAYS[0]) & (ev["start"] < TEST_DAYS[1])
    ev.sort_values(["cam_id", "start"]).round(3).to_csv(OUT / "catalog.csv", index=False)
    print(f"{len(ev)} outages at {ev['cam_id'].nunique()} cameras; {calls} NIMS calls; "
          f"{int((ev['camera_daylight_frames'] >= 3).sum())} with ≥ 3 daylight camera frames")


def site_features(cam: str):
    """All cached scene features for a site: t, h (NaN where the gauge had nothing), F, filename."""
    metas, feats = [], []
    for name in ("scene_history_all.npz", "scene_kill30_fit.npz"):
        p = DATA / "derived" / cam / name
        if p.exists():
            z = np.load(p)
            metas.append(pd.DataFrame({"t": pd.to_datetime(z["t"], utc=True), "h": z["h"], "fn": z["filename"],
                                       "src": len(feats), "k": np.arange(len(z["t"]))}))
            feats.append(z["F"])
    if not metas:
        return None
    df = pd.concat(metas, ignore_index=True).drop_duplicates("fn").sort_values("t").reset_index(drop=True)
    return df, feats


def score(min_frames: int = 3):
    from riversight.onboard.cv import _scene_tune, frozen_cfg, predict_fold
    cfg = frozen_cfg()
    cat = pd.read_csv(OUT / "catalog.csv", dtype={"nwis_id": str}, parse_dates=["start", "end"])
    kill, onb = kill_sites(), onboarded_sites()
    cand = cat[cat["cam_id"].isin(set(kill) | set(onb)) & ~cat["in_frozen_test_days"].astype(bool)]
    rows, frames_out = [], []
    for cam, evs in cand.groupby("cam_id"):
        cut = KILL_CUT if cam in kill else pd.Timestamp(W_END)
        st = _scene_tune(cut)
        g = st.gauge_series(cam)
        S = site_features(cam)
        if S is None:
            continue
        df, feats = S
        df = df[df["t"] < cut].reset_index(drop=True)
        iv = pd.read_parquet(DATA / "raw" / "iv_12m" / f"{str(evs['nwis_id'].iloc[0]).zfill(8)}.parquet")
        iv = iv.set_index("time").sort_index()
        X = np.stack([feats[s][k] for s, k in zip(df["src"], df["k"])]).astype(np.float32)
        for e in evs.itertuples():
            inside = ((df["t"] > e.start) & (df["t"] < e.end)).to_numpy()
            if inside.sum() < min_frames:
                continue
            win = ((df["t"] >= e.start - pd.Timedelta("2D")) & (df["t"] < e.end + pd.Timedelta("1D"))).to_numpy()
            has_h = np.isfinite(df["h"].to_numpy())
            for variant, tr in (("excl7d", has_h & ~((df["t"] >= e.start - PAD) & (df["t"] <= e.end + PAD)).to_numpy()),
                                ("causal", has_h & (df["t"] < e.start - PAD).to_numpy())):
                if tr.sum() < 200:
                    rows.append({"cam_id": cam, "start": e.start, "end": e.end, "variant": variant, "status": f"too little training ({int(tr.sum())})"})
                    continue
                t_tr = pd.DatetimeIndex(df["t"][tr])
                p = predict_fold(X[tr], df["h"].to_numpy()[tr], t_tr[-1], X[win], pd.DatetimeIndex(df["t"][win]), g, cfg)
                sel = inside[win]
                tt = pd.DatetimeIndex(df["t"][win][sel])
                pc = p[sel]
                # USGS's backfill at frame time (estimated values), nearest within 10 min
                truth = iv["value"].reindex(tt, method="nearest", tolerance=pd.Timedelta("10min")).to_numpy(float)
                qual = iv["quals"].reindex(tt, method="nearest", tolerance=pd.Timedelta("10min")).fillna("").to_numpy()
                is_e = np.array(["e" in str(q).split(",") for q in qual]) & np.isfinite(truth)
                lkv = float(e.v_before)
                r = {"cam_id": cam, "start": e.start, "end": e.end, "hours": float(e.hours), "kinds": e.kinds, "codes": e.codes,
                     "truth": e.truth, "variant": variant, "status": "scored", "n_frames": int(sel.sum()), "n_truth": int(is_e.sum()),
                     "n_train": int(tr.sum()), "v_before": lkv, "v_after": float(e.v_after),
                     "stage_range_in_outage": float(np.nanmax(truth[is_e]) - np.nanmin(truth[is_e])) if is_e.any() else np.nan}
                if is_e.any():
                    r["cam_mae"] = float(np.mean(np.abs(pc[is_e] - truth[is_e])))
                    r["lkv_mae"] = float(np.mean(np.abs(lkv - truth[is_e]))) if np.isfinite(lkv) else np.nan
                    r["cam_median_ae"] = float(np.median(np.abs(pc[is_e] - truth[is_e])))
                    r["cam_beats_lkv"] = bool(r["cam_mae"] < r["lkv_mae"]) if np.isfinite(r["lkv_mae"]) else None
                last = tt >= e.end - pd.Timedelta("6h")
                if last.any() and np.isfinite(e.v_after):
                    r["cam_end_err"] = float(abs(pc[last][-1] - e.v_after))
                    r["lkv_end_err"] = float(abs(lkv - e.v_after)) if np.isfinite(lkv) else np.nan
                    r["end_frame_age_h"] = float((e.end - tt[last][-1]).total_seconds() / 3600)
                rows.append(r)
                for ti, pi, hi, ei in zip(tt, pc, truth, is_e):
                    frames_out.append({"cam_id": cam, "outage_start": e.start, "variant": variant, "t": ti, "camera_ft": pi,
                                       "usgs_estimated_ft": hi if ei else np.nan, "lkv_ft": lkv})
        print(f"{cam}: {len(evs)} outages checked", flush=True)
    sc = pd.DataFrame(rows)
    sc.round(4).to_csv(OUT / "scored.csv", index=False)
    pd.DataFrame(frames_out).round(4).to_csv(OUT / "scored_frames.csv", index=False)
    ok = sc[sc.get("status", pd.Series(dtype=str)) == "scored"] if len(sc) else sc
    print(f"{len(ok)} scored (outage × variant) rows")


def readme():
    """README.md generated from catalog.csv + scored.csv (numbers are never typed by hand)."""
    cat = pd.read_csv(OUT / "catalog.csv", parse_dates=["start", "end"])
    raw = pd.read_csv(OUT / "catalog_gauges.csv")
    pool = pd.read_csv(OUT.parent / "onboarding" / "pool.csv")
    n_g = int(pool.loc[pool["iv_n"] > 0, "nwis_id"].nunique())
    with_out = cat["nwis_id"].nunique()
    checked = cat[cat["camera_daylight_frames"].notna()]
    seen = checked[checked["camera_daylight_frames"] >= 3]
    L = ["# Real gauge outages at HIVIS camera sites (SPRINT W5 Part B)", "",
         f"Generated by `scripts/onboard_outages.py --readme` from `catalog.csv` and `scored.csv`. Window "
         f"{W_START.date()} – {W_END.date()} (USGS IV 00065, legacy NWIS IV with qualifiers, `scripts/onboard_scan.py`).", "",
         "## How often gauges at camera sites go dark", "",
         f"- Gauges with 00065 data in the window: **{n_g}** (of {pool['nwis_id'].nunique()} distinct gauges behind gauged HIVIS cameras).",
         f"- Gauges with at least one outage ≥ 6 h (gap, USGS-estimated backfill, or equipment/ice-qualified run): **{with_out}** "
         f"({with_out / max(n_g, 1):.0%}).",
         f"- Outages after merging overlapping runs: **{len(cat)}**; median length {cat['hours'].median():.1f} h; "
         f"{int((cat['hours'] >= 24).sum())} last ≥ 24 h, {int((cat['hours'] >= 24 * 7).sum())} ≥ 7 days.",
         f"- By kind (raw runs before merging): " + ", ".join(f"{k} {v}" for k, v in raw["kind"].value_counts().items()) + ".",
         f"- Camera frames checked for {len(checked)} outages (cached listings or one NIMS listing each): "
         f"**{len(seen)}** had ≥ 3 daylight camera frames while the gauge was out "
         f"({len(seen) / max(len(checked), 1):.0%} of those checked).", ""]
    sp = OUT / "scored.csv"
    if sp.exists() and sp.stat().st_size > 5:
        sc = pd.read_csv(sp, parse_dates=["start", "end"])
        ok = sc[sc["status"] == "scored"] if "status" in sc else sc.iloc[0:0]
        L += ["## Camera through the outage (calibrated sites)", "",
              "Frozen D-0007 setting. `excl7d` = refit without the outage ± 7 days; `causal` = refit on data before the "
              "outage − 7 days only. Truth: USGS's later estimated backfill at frame time where it exists; otherwise the "
              "first reading after the gauge returned vs the camera's last reading in the outage's final 6 h. "
              "Baseline: last-known value before the outage. Outages overlapping the frozen test days are excluded "
              "at the 20 kill-test sites.", ""]
        if len(ok):
            L += ["| site | start (UTC) | hours | kinds | variant | frames | truth pts | camera MAE | last-known MAE | "
                  "end err cam / LKV |", "|---|---|---|---|---|---|---|---|---|---|"]
            f = lambda x: "–" if pd.isna(x) else f"{x:.2f}"  # noqa: E731
            for r in ok.sort_values(["cam_id", "start", "variant"]).itertuples():
                L.append(f"| {r.cam_id} | {r.start:%Y-%m-%d %H:%M} | {r.hours:.0f} | {r.kinds} | {r.variant} | {r.n_frames} | "
                         f"{r.n_truth} | {f(getattr(r, 'cam_mae', np.nan))} | {f(getattr(r, 'lkv_mae', np.nan))} | "
                         f"{f(getattr(r, 'cam_end_err', np.nan))} / {f(getattr(r, 'lkv_end_err', np.nan))} |")
            end = ok.dropna(subset=["cam_end_err", "lkv_end_err"]).copy()
            end["moved"] = (end["v_after"] - end["v_before"]).abs()
            for v in ("excl7d", "causal"):
                d = end[end["variant"] == v]
                if not len(d):
                    continue
                m = d[d["moved"] >= 0.25]
                L += ["", f"- `{v}`, hard gaps scored at the gauge's return: camera closer than last-known value in "
                          f"**{int((d['cam_end_err'] < d['lkv_end_err']).sum())}/{len(d)}**. In {len(d) - len(m)} of them the "
                          f"river moved < 0.25 ft during the gap, where holding the last reading is nearly exact. "
                          f"Gaps where it moved ≥ 0.25 ft: {len(m)}, camera closer in "
                          f"**{int((m['cam_end_err'] < m['lkv_end_err']).sum())}/{len(m)}**"
                          + (": " + "; ".join(f"{r.cam_id} ({r.hours:.0f} h, moved {r.moved:.2f} ft): camera "
                                               f"{r.cam_end_err:.2f} vs last-known {r.lkv_end_err:.2f} ft"
                                               for r in m.itertuples()) if len(m) else "") + "."]
            dense = ok[ok["n_truth"] > 0] if "n_truth" in ok else ok.iloc[0:0]
            for v in ("excl7d", "causal"):
                d = dense[dense["variant"] == v]
                if len(d):
                    L.append("")
                    L.append(f"- `{v}`, outages with dense truth: {len(d)}; camera beats last-known value in "
                             f"**{int(d['cam_beats_lkv'].fillna(False).astype(bool).sum())}/{len(d)}**; median camera MAE "
                             f"{d['cam_mae'].median():.2f} ft vs last-known {d['lkv_mae'].median():.2f} ft.")
        else:
            L.append("No outage at a calibrated site had ≥ 3 registered daylight frames with features. Catalogue only.")
    (OUT / "README.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'README.md'} ({len(L)} lines)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--readme", action="store_true")
    ap.add_argument("--max-calls", type=int, default=1200)
    ap.add_argument("--pace", type=float, default=1.5)
    a = ap.parse_args()
    if a.catalog:
        catalog(a.max_calls, a.pace)
    if a.score:
        score()
    if a.readme or a.catalog or a.score:
        readme()


if __name__ == "__main__":
    main()
