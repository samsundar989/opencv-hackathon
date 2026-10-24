"""12 months of USGS IV gage height (00065) for every gauged HIVIS camera, with qualifiers, and the outage scan.

Legacy NWIS IV (WaterML-JSON) carries per-value qualifier codes: A/P (approved/provisional), e (estimated —
the gauge was out and USGS filled it in afterwards), and equipment/ice codes (Eqp, Ice, Dis, Mnt, ...).
A hard outage is a run of missing timestamps; an estimated run is a backfilled outage with dense truth.
Values equal to the series noDataValue are kept as NaN so their qualifiers survive.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from riversight.data.nwis import LEGACY_IV, PARAM_STAGE, _iso, check_rate_limit

STATUS = {"A", "P"}                         # approval codes, not outage evidence
OUTAGE_CODES = {"Eqp", "Ice", "Dis", "Mnt", "Ssn", "Bkw", "Fld", "Pr", "Rat", "Zfl", "***", "--"}


def parse_waterml_qualified(data: dict) -> dict[str, pd.DataFrame]:
    """WaterML-JSON → {site_no: DataFrame(time UTC, value float|NaN, quals 'A,e' string)}; longest series per site."""
    out: dict[str, pd.DataFrame] = {}
    for ts in data.get("value", {}).get("timeSeries", []):
        site = ts["sourceInfo"]["siteCode"][0]["value"]
        nodata = float(ts.get("variable", {}).get("noDataValue", -999999.0))
        for block in ts.get("values", []):
            rows = []
            for v in block.get("value", []):
                try:
                    x = float(v.get("value"))
                except (TypeError, ValueError):
                    x = np.nan
                rows.append((v["dateTime"], np.nan if x == nodata else x, ",".join(v.get("qualifiers") or [])))
            if not rows:
                continue
            df = pd.DataFrame(rows, columns=["time", "value", "quals"])
            df["time"] = pd.to_datetime(df["time"], utc=True, format="ISO8601")
            if site not in out or len(df) > len(out[site]):
                out[site] = df.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    return out


def fetch_iv_qualified(http: httpx.Client, sites: list[str], start: datetime, end: datetime,
                       parameter: str = PARAM_STAGE) -> dict[str, pd.DataFrame]:
    r = http.get(LEGACY_IV, params={"sites": ",".join(sites), "parameterCd": parameter, "startDT": _iso(start),
                                    "endDT": _iso(end), "format": "json", "siteStatus": "all"})
    check_rate_limit(r)
    if r.status_code == 404:                 # no 00065 at any site in the batch
        return {}
    r.raise_for_status()
    return parse_waterml_qualified(r.json())


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[i0, i1] inclusive index runs where mask is True."""
    m = np.concatenate([[False], mask, [False]]).astype(np.int8)
    d = np.diff(m)
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1) - 1))


def scan_outages(df: pd.DataFrame, min_gap_h: float = 6.0) -> list[dict]:
    """Outage events in one site's IV record.

    kind = 'gap'        no published value for ≥ min_gap_h (start/end = last value before / first after);
           'estimated'  ≥ min_gap_h of values qualified 'e' (USGS backfill after an outage);
           'qualified'  ≥ min_gap_h of values carrying an equipment/ice code (or NaN with any non-A/P code).
    Missing data before the first / after the last value is not an outage (new or retired gauge)."""
    ev: list[dict] = []
    if df is None or not len(df):
        return ev
    df = df.sort_values("time").reset_index(drop=True)
    t = df["time"]
    v = df["value"].to_numpy(float)
    has = np.isfinite(v)
    tv = t[has].reset_index(drop=True)
    vv = v[has]
    if len(tv) >= 2:
        dt_h = tv.diff().dt.total_seconds().to_numpy() / 3600
        for i in np.flatnonzero(dt_h >= min_gap_h):
            ev.append({"kind": "gap", "start": tv[i - 1], "end": tv[i], "hours": float(dt_h[i]),
                       "v_before": float(vv[i - 1]), "v_after": float(vv[i]), "codes": ""})
    q =df["quals"].fillna("").str.split(",")
    est = q.map(lambda c: "e" in c).to_numpy()
    for i0, i1 in _runs(est):
        h = (t[i1] - t[i0]).total_seconds() / 3600
        if h >= min_gap_h:
            ev.append({"kind": "estimated", "start": t[i0], "end": t[i1], "hours": float(h),
                       "v_before": float(v[i0 - 1]) if i0 > 0 else np.nan,
                       "v_after": float(v[i1 + 1]) if i1 + 1 < len(v) else np.nan, "codes": "e"})
    code = q.map(lambda c: next((x for x in c if x in OUTAGE_CODES), "")).to_numpy()
    flagged = (code != "") | (~has & q.map(lambda c: any(x and x not in STATUS for x in c)).to_numpy())
    for i0, i1 in _runs(flagged):
        h = (t[i1] - t[i0]).total_seconds() / 3600
        if h >= min_gap_h:
            codes = sorted({c for c in code[i0:i1 + 1] if c} | {x for c in q[i0:i1 + 1] for x in c if x and x not in STATUS})
            ev.append({"kind": "qualified", "start": t[i0], "end": t[i1], "hours": float(h),
                       "v_before": float(v[i0 - 1]) if i0 > 0 else np.nan,
                       "v_after": float(v[i1 + 1]) if i1 + 1 < len(v) else np.nan, "codes": "|".join(codes)})
    return sorted(ev, key=lambda e: e["start"])


def stage_stats(df: pd.DataFrame) -> dict:
    v = df["value"].dropna().to_numpy(float) if df is not None and len(df) else np.array([])
    if not len(v):
        return {"iv_n": 0, "iv_p05": np.nan, "iv_p95": np.nan, "iv_swing_ft": np.nan, "iv_first": "", "iv_last": ""}
    p05, p95 = np.quantile(v, [0.05, 0.95])
    tt = df.loc[df["value"].notna(), "time"]
    return {"iv_n": int(len(v)), "iv_p05": float(p05), "iv_p95": float(p95), "iv_swing_ft": float(p95 - p05),
            "iv_max_minus_p50": float(v.max() - np.median(v)), "iv_first": str(tt.min()), "iv_last": str(tt.max())}


def cache_path(root: Path, site: str) -> Path:
    return root / f"{site}.parquet"
