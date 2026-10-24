"""Pre-registered prospective live evaluation (D-0010 §1, window per D-0011 W1-7).

Models under test: the live bundles served in the first COOL cycle (results/live_prospective/frozen_models.json).
Window: from that cycle (2026-10-23T21:28:10Z) on; earlier readings are excluded. Submission cut: Mon Oct 26 12:00 CT;
the scorer keeps running through Nov 9.

Scored: every daylight reading with registration OK whose model_sha is a frozen one, against the USGS gauge
reading closest in time to the frame within ±20 min (fetched fresh from NWIS IV, not the cycle's own gauge value).
OUT_OF_RANGE readings are counted separately ("saturated, gauge trusted"), never as camera numbers.
Baseline: the gauge's own last-known value 24 h before the frame.

Outputs (store keys and, when committed, results/live_prospective/): readings.csv, per_site.csv, summary.json.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

WINDOW_START = pd.Timestamp("2026-10-23T21:28:10Z")
SUBMISSION_CUT = pd.Timestamp("2026-10-26T17:00:00Z")      # Mon Oct 26 12:00 CDT
MATCH_MIN = 20
WITHIN_FT = 0.25


def load_readings(store, cams: list[str], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for day in pd.date_range(start.floor("D"), end.floor("D"), freq="D"):
        for cam in cams:
            b = store.get_bytes(f"live/sites/{cam}/{day:%Y-%m-%d}.jsonl")
            for line in (b or b"").decode().splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("mode", "live") != "live":
                    continue
                rows.append({"cam_id": r["cam_id"], "t_frame": r["t_frame"], "t_cycle": r["t_cycle"],
                             "daylight": r.get("daylight"), "reg_ok": (r.get("registration") or {}).get("ok"),
                             "model_sha": r.get("model_sha"), "camera_ft": r.get("camera_stage_ft"),
                             "camera_at_least_ft": r.get("camera_at_least_ft"), "shadow_ft": r.get("shadow_stage_ft"),
                             "flags": "|".join(r.get("flags", [])),
                             "status": r.get("status"), "agent_actions": "|".join((r.get("agent") or {}).get("actions") or [])})
    df = pd.DataFrame(rows)
    if not len(df):
        return df
    df["t_frame"] = pd.to_datetime(df["t_frame"], utc=True)
    df["t_cycle"] = pd.to_datetime(df["t_cycle"], utc=True)
    return df[(df["t_cycle"] >= start) & (df["t_cycle"] <= end)].drop_duplicates(["cam_id", "t_frame"]).reset_index(drop=True)


def fetch_gauge(nwis: dict[str, str], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, pd.Series]:
    from riversight.data.nwis import legacy_iv_multi
    got = legacy_iv_multi(sorted(set(nwis.values())), (start - pd.Timedelta("26h")).to_pydatetime(),
                          (end + pd.Timedelta("30min")).to_pydatetime(), timeout=120)
    return {k: pd.Series(v["value"].to_numpy(float), index=pd.DatetimeIndex(v["time"])) for k, v in got.items()}


def match(series: pd.Series | None, t: pd.Timestamp, tol_min: float = MATCH_MIN) -> float:
    if series is None or not len(series):
        return np.nan
    i = series.index.get_indexer([t], method="nearest")[0]
    return float(series.iloc[i]) if abs((series.index[i] - t).total_seconds()) <= tol_min * 60 else np.nan


def last_known(series: pd.Series | None, t: pd.Timestamp) -> float:
    if series is None:
        return np.nan
    s = series[series.index <= t]
    return float(s.iloc[-1]) if len(s) else np.nan


def score(df: pd.DataFrame, frozen: dict, gauges: dict[str, pd.Series], nwis: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    df = df.copy()
    sha = {c: v["model_sha"][:12] for c, v in frozen["models"].items()}
    df["frozen_model"] = [sha.get(c) == m for c, m in zip(df["cam_id"], df["model_sha"])]
    df["gauge_ft"] = [match(gauges.get(nwis[c]), t) for c, t in zip(df["cam_id"], df["t_frame"])]
    df["lkv24_ft"] = [last_known(gauges.get(nwis[c]), t - pd.Timedelta("24h")) for c, t in zip(df["cam_id"], df["t_frame"])]
    eligible = df["daylight"].astype(bool) & df["reg_ok"].astype(bool) & df["frozen_model"]
    df["saturated"] = eligible & df["camera_at_least_ft"].notna()
    df["scored"] = eligible & df["camera_ft"].notna() & df["gauge_ft"].notna() & ~df["saturated"]
    df["abs_err"] = np.where(df["scored"], (df["camera_ft"] - df["gauge_ft"]).abs(), np.nan)
    df["lkv24_abs_err"] = np.where(df["scored"] & df["lkv24_ft"].notna(), (df["lkv24_ft"] - df["gauge_ft"]).abs(), np.nan)
    if "shadow_ft" not in df:
        df["shadow_ft"] = np.nan
    df["shadow_abs_err"] = np.where(df["scored"] & df["shadow_ft"].notna(), (df["shadow_ft"] - df["gauge_ft"]).abs(), np.nan)

    def agg(g: pd.DataFrame) -> dict:
        s = g[g["scored"]]
        day = g[g["daylight"].astype(bool)]
        return {"readings": int(len(g)), "daylight_readings": int(len(day)), "scored": int(len(s)),
                "saturated_gauge_trusted": int(g["saturated"].sum()),
                "coverage_pct": round(100 * len(s) / len(day), 1) if len(day) else None,
                "mae_ft": round(float(s["abs_err"].mean()), 3) if len(s) else None,
                "median_ae_ft": round(float(s["abs_err"].median()), 3) if len(s) else None,
                "within_025_pct": round(100 * float((s["abs_err"] <= WITHIN_FT).mean()), 1) if len(s) else None,
                "lkv24_mae_ft": round(float(s["lkv24_abs_err"].mean()), 3) if s["lkv24_abs_err"].notna().any() else None,
                "lkv24_median_ae_ft": round(float(s["lkv24_abs_err"].median()), 3) if s["lkv24_abs_err"].notna().any() else None,
                # v2 shadow on the same readings (D-0010 §2 criterion 2: no worse than v1's median AE)
                "shadow_n": int(s["shadow_abs_err"].notna().sum()),
                "shadow_median_ae_ft": round(float(s["shadow_abs_err"].median()), 3) if s["shadow_abs_err"].notna().any() else None,
                "v1_median_ae_on_shadow_rows_ft": round(float(s.loc[s["shadow_abs_err"].notna(), "abs_err"].median()), 3)
                if s["shadow_abs_err"].notna().any() else None,
                "flags": {f: int(g["flags"].str.contains(f).sum()) for f in
                          ("VIEW_CHANGE", "LOW_QUALITY", "GAUGE_STALE", "DISAGREE", "RISING", "OUT_OF_RANGE")},
                "agent_actions": pd.Series([a for x in g["agent_actions"] for a in x.split("|") if a]).value_counts().to_dict()}

    per_site = pd.DataFrame([{"cam_id": c, **{k: v for k, v in agg(g).items() if not isinstance(v, dict)}}
                             for c, g in df.groupby("cam_id")])
    fleet = agg(df)
    s = df[df["scored"]]
    summary = {
        "decision": "D-0010 §1 (window D-0011 W1-7)", "window_start_utc": WINDOW_START.isoformat(),
        "submission_cut_utc": SUBMISSION_CUT.isoformat(), "scored_until_utc": df["t_cycle"].max().isoformat() if len(df) else None,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "models": "frozen live models (results/live_prospective/frozen_models.json)",
        "fleet": fleet, "sites_scored": int(s["cam_id"].nunique()),
        "median_of_site_mae_ft": round(float(per_site["mae_ft"].dropna().median()), 3) if per_site["mae_ft"].notna().any() else None,
        "sites_camera_beats_lkv24": int(((per_site["mae_ft"] < per_site["lkv24_mae_ft"]) & per_site["mae_ft"].notna()).sum()),
        "rules": {"match": f"closest USGS IV reading within ±{MATCH_MIN} min of the frame",
                  "eligible": "daylight, registration OK, frozen model_sha", "saturated": "OUT_OF_RANGE: counted, not scored",
                  "baseline": "gauge last-known value 24 h before the frame"},
    }
    return df, per_site, summary


def run(store, frozen: dict, end: pd.Timestamp | None = None) -> dict:
    end = end or pd.Timestamp.now(tz="UTC")
    cams = sorted(frozen["models"])
    nwis = {c: frozen["models"][c]["nwis_id"] for c in cams}
    df = load_readings(store, cams, WINDOW_START, end)
    if not len(df):
        return {"note": "no readings yet"}
    df, per_site, summary = score(df, frozen, fetch_gauge(nwis, WINDOW_START, end), nwis)
    for name, frame in (("readings.csv", df), ("per_site.csv", per_site)):
        buf = io.StringIO()
        frame.to_csv(buf, index=False, float_format="%.4f")
        store.put_bytes(f"live/prospective/{name}", buf.getvalue().encode(), "text/csv", "no-cache")
    store.put_json("live/prospective/summary.json", summary)
    return summary
