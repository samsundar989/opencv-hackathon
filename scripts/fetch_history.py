"""SLICE_01B step 2: long calibration history for the kill-test sites (D-0006).

Per site:
  1. NIMS listing of the 12-month history window [2025-10-03, 2026-10-03) in 10-day chunks
     (exact per-week coverage) + one 1-day probe per week from 2025-01 to the window start
     (coverage table only). Cached: data/derived/<cam>/history/list.txt, coverage.csv.
  2. Gauge stage (00065) for the window from the OGC API (legacy NWIS IV fallback, identical values —
     D-0005a). Cached: history/stage.parquet.
  3. Selection: daylight (sun ≥ 3°) frames nearest each even UTC hour (±10 min), plus every hourly
     frame on UTC days whose stage range ≥ 0.5 ft.
  4. Download the selected 720-px frames (≤ 4 parallel, cached under data/raw/720/<cam>/).
  5. history/frames.parquet (filename, time, stage_ft, path, event_day) and results/history/coverage*.csv.

Polite by construction: NIMS calls are sequential and paced (`--pace` s), 429/5xx back off, every
listing/stage/image is cached and never re-fetched. Run via worker-q (low priority, D-0005).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from riversight.data.join import frames_table, join_frames_to_stage  # noqa: E402
from riversight.data.nims import NimsClient  # noqa: E402
from riversight.data.nwis import NwisClient, RateLimited, legacy_iv_multi  # noqa: E402
from riversight.killtest import sun_elevation_deg  # noqa: E402

DATA = Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))
H_START = datetime(2025, 10, 3, tzinfo=timezone.utc)
H_END = datetime(2026, 10, 3, tzinfo=timezone.utc)      # history ends 1 day before the frozen test days
PROBE_FROM = datetime(2025, 1, 6, tzinfo=timezone.utc)
SUN_MIN = 3.0
EVENT_DAY_FT = 0.5


def _progress(frac: float):
    p = os.environ.get("WORKERQ_PROGRESS")
    if p:
        try:
            Path(p).write_text(f"{frac:.4f}")
        except OSError:
            pass


class Paced:
    """Sequential NIMS listing calls, ≥ `pace` s apart; sleeps out long rate limits instead of retrying."""

    def __init__(self, nims: NimsClient, pace: float, api_key: str | None):
        self.nims, self.pace, self.last, self.n = nims, pace, 0.0, 0
        self.key = api_key

    def list(self, cam, after, before):
        while True:
            dt = time.time() - self.last
            if dt < self.pace:
                time.sleep(self.pace - dt)
            self.last = time.time()
            self.n += 1
            try:
                return self.nims.list_files(cam, after=after, before=before, limit=1000, recent=False)
            except RateLimited as e:
                print(f"  NIMS rate limit; sleeping {e.retry_after_s:.0f}s", flush=True)
                time.sleep(e.retry_after_s + 5)

    def range(self, cam, start, end, chunk_days=10):
        out, t = [], start
        while t < end:
            t2 = min(t + timedelta(days=chunk_days), end)
            fs = self.list(cam, t, t2)
            if len(fs) >= 1000:
                mid = t + (t2 - t) / 2
                fs = self.range(cam, t, mid, chunk_days) + self.range(cam, mid, t2, chunk_days)
            out += fs
            t = t2
        return sorted(set(out))


def listing(P: Paced, cam: str, d: Path) -> tuple[list[str], pd.DataFrame]:
    lp, cp = d / "list.txt", d / "coverage.csv"
    if lp.exists() and cp.exists():
        return [x for x in lp.read_text().splitlines() if x], pd.read_csv(cp)
    files = P.range(cam, H_START, H_END)
    ft = frames_table(files)
    rows = []
    # weekly coverage inside the window from the full listing
    wk = pd.date_range(H_START, H_END, freq="7D")
    for w0 in wk[:-1]:
        n = int(((ft["time"] >= w0) & (ft["time"] < w0 + pd.Timedelta("7D"))).sum()) if len(ft) else 0
        rows.append({"week_start": w0.date().isoformat(), "kind": "full_listing", "n_frames": n,
                     "days_with_frames": int(ft.loc[(ft["time"] >= w0) & (ft["time"] < w0 + pd.Timedelta("7D")), "time"].dt.date.nunique()) if len(ft) else 0})
    # one 1-day probe per week before the window
    t = PROBE_FROM
    while t < H_START:
        probe = t + timedelta(days=2)
        n = len(P.list(cam, probe, probe + timedelta(days=1)))
        rows.append({"week_start": t.date().isoformat(), "kind": "probe_1day", "n_frames": n, "days_with_frames": int(n > 0)})
        t += timedelta(days=7)
    cov = pd.DataFrame(rows).sort_values("week_start")
    d.mkdir(parents=True, exist_ok=True)
    lp.write_text("\n".join(files))
    cov.to_csv(cp, index=False)
    return files, cov


def stage_history(nwis: NwisClient, nwis_id: str, d: Path) -> pd.DataFrame:
    sp = d / "stage.parquet"
    if sp.exists():
        return pd.read_parquet(sp)
    s0, s1 = H_START - timedelta(days=2), H_END + timedelta(hours=1)
    try:
        st = nwis.stage(nwis_id, s0, s1)[["time", "value"]].assign(source="ogc")
    except RateLimited as e:
        print(f"  OGC rate limited ({e.retry_after_s:.0f}s); legacy IV fallback", flush=True)
        st = pd.DataFrame(columns=["time", "value"])
    if not len(st):
        got = legacy_iv_multi([nwis_id], s0, s1)
        st = got.get(nwis_id, pd.DataFrame(columns=["time", "value"])).assign(source="nwis_iv_legacy")
    st.to_parquet(sp, index=False)
    return st


def select(ft: pd.DataFrame, stage: pd.DataFrame, lat: float, lng: float) -> pd.DataFrame:
    if not len(ft):
        return ft.assign(event_day=False)
    ft = ft[(ft["time"] >= H_START) & (ft["time"] < H_END)].copy()
    ft["sun"] = sun_elevation_deg(lat, lng, ft["time"])
    ft = ft[ft["sun"] >= SUN_MIN].copy()
    s = stage.dropna(subset=["value"]).copy()
    s["day"] = s["time"].dt.floor("D")
    rngs = s.groupby("day")["value"].agg(lambda v: v.max() - v.min())
    ev_days = set(rngs[rngs >= EVENT_DAY_FT].index)
    ft["mark"] = ft["time"].dt.round("h")
    ft["off"] = (ft["time"] - ft["mark"]).abs()
    ft = ft[ft["off"] <= pd.Timedelta("10min")]
    ft["event_day"] = ft["mark"].dt.floor("D").isin(ev_days)
    keep = ft[(ft["mark"].dt.hour % 2 == 0) | ft["event_day"]]
    return keep.sort_values("off").drop_duplicates("mark").sort_values("time").drop(columns=["off"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", type=Path, default=DATA / "sites" / "kill_test.yaml")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--pace", type=float, default=2.4, help="seconds between NIMS listing calls")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--env-file", type=Path)
    ap.add_argument("--list-only", action="store_true")
    a = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(a.env_file or (ROOT / ".env"))
    key = os.getenv("USGS_API_KEY")
    sites = [s for s in yaml.safe_load(a.sites.read_text(encoding="utf-8"))["sites"] if not a.only or s["cam_id"] in a.only]
    nims, nwis = NimsClient(api_key=key), NwisClient(api_key=key)
    P = Paced(nims, a.pace, key)
    raw = DATA / "raw"
    summary, sel_all = [], {}
    for i, s in enumerate(sites):
        cam, nid = s["cam_id"], str(s["nwis_id"]).zfill(8)
        d = DATA / "derived" / cam / "history"
        t0 = time.time()
        files, cov = listing(P, cam, d)
        st = stage_history(nwis, nid, d)
        sel = select(frames_table(files), st, float(s["lat"]), float(s["lng"]))
        sel_all[cam] = sel
        full = cov[cov["kind"] == "full_listing"]
        pre = cov[cov["kind"] == "probe_1day"]
        days = int(sel["time"].dt.floor("D").nunique()) if len(sel) else 0
        summary.append({"cam_id": cam, "listed_frames_12m": len(files),
                        "weeks_with_frames_12m": int((full["n_frames"] > 0).sum()), "weeks_12m": len(full),
                        "first_frame": str(frames_table(files)["time"].min()) if files else "",
                        "probe_weeks_with_frames_pre": int((pre["n_frames"] > 0).sum()), "probe_weeks_pre": len(pre),
                        "stage_points": len(st), "stage_source": st["source"].iloc[0] if len(st) else "",
                        "selected_frames": len(sel), "selected_event_day_frames": int(sel["event_day"].sum()) if len(sel) else 0,
                        "days_with_selected_frames": days})
        print(f"[{i+1}/{len(sites)}] {cam}: {len(files)} listed, {len(sel)} selected over {days} days, "
              f"stage {len(st)} pts ({time.time()-t0:.0f}s, {P.n} NIMS calls so far)", flush=True)
        _progress(0.4 * (i + 1) / len(sites))
    out = ROOT / "results" / "history"
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summary).to_csv(out / "coverage_summary.csv", index=False)
    pd.concat([pd.read_csv(DATA / "derived" / s["cam_id"] / "history" / "coverage.csv").assign(cam_id=s["cam_id"])
               for s in sites]).to_csv(out / "coverage_weekly.csv", index=False)
    if a.list_only:
        return
    jobs = [(cam, f) for cam, sel in sel_all.items() for f in sel["filename"] if not (raw / "720" / cam / f).exists()]
    print(f"{len(jobs)} images to download", flush=True)
    errs, t0 = [], time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(nims.download, cam, f, raw, "720"): (cam, f) for cam, f in jobs}
        for k, fu in enumerate(as_completed(futs), 1):
            try:
                fu.result()
            except Exception as e:
                errs.append((*futs[fu], repr(e)[:120]))
            if k % 500 == 0:
                print(f"  {k}/{len(jobs)} {time.time()-t0:.0f}s, {len(errs)} errors", flush=True)
                _progress(0.4 + 0.6 * k / len(jobs))
    for s in sites:
        cam = s["cam_id"]
        d = DATA / "derived" / cam / "history"
        sel = sel_all[cam]
        st = pd.read_parquet(d / "stage.parquet")
        j = join_frames_to_stage(sel[["filename", "cam_id", "time"]], st)
        j = j.merge(sel[["filename", "event_day"]], on="filename")
        j = j[[(raw / "720" / cam / f).exists() for f in j["filename"]]]
        j["path"] = [str(Path("data") / "raw" / "720" / cam / f) for f in j["filename"]]   # repo-relative, like SLICE_01
        j.to_parquet(d / "frames.parquet", index=False)
        print(f"{cam}: {len(j)} history frames on disk, {j['stage_ft'].notna().sum()} with stage", flush=True)
    print(f"done; {len(errs)} download errors")
    for e in errs[:20]:
        print("ERR", *e)


if __name__ == "__main__":
    main()
