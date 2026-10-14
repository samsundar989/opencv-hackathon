"""USGS Water Data OGC API client — instantaneous gage height (parameter 00065, feet).

Verified endpoint (2026-10-13):
  GET https://api.waterdata.usgs.gov/ogcapi/v1/collections/continuous/items
      ?monitoring_location_id=USGS-<site>&parameter_code=00065&datetime=<start>/<end>&limit=<n>&f=json[&api_key=...]
Response: GeoJSON FeatureCollection; feature.properties has time (ISO, +00:00), value (string, ft),
unit_of_measure, approval_status, qualifier, statistic_id ('00011' = instantaneous), time_series_id.
Pagination: follow links[rel=next].
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import pandas as pd
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

OGC_BASE = "https://api.waterdata.usgs.gov/ogcapi/v1"
PARAM_STAGE = "00065"
PARAM_DISCHARGE = "00060"


class _Transient(Exception):
    pass


class RateLimited(RuntimeError):
    """The API said 'come back later' for longer than we are willing to sleep. Do not retry blindly:
    every retried request also counts against the hourly quota (1000/h per key on Oct 14)."""

    def __init__(self, retry_after_s: float):
        super().__init__(f"USGS rate limit hit; retry after {retry_after_s:.0f}s")
        self.retry_after_s = retry_after_s


MAX_POLITE_SLEEP_S = 90.0


def check_rate_limit(r: httpx.Response) -> None:
    """Raise RateLimited on 429 with a long Retry-After; _Transient on short waits/5xx."""
    if r.status_code == 429:
        try:
            ra = float(r.headers.get("retry-after", "0"))
        except ValueError:
            ra = 0.0
        if ra > MAX_POLITE_SLEEP_S:
            raise RateLimited(ra)
        raise _Transient(f"429 (retry-after {ra:.0f}s)")
    if r.status_code in (500, 502, 503, 504):
        raise _Transient(f"{r.status_code} for {r.url}")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def features_to_frame(features: list[dict]) -> pd.DataFrame:
    """Flatten OGC features into a tidy frame: time (UTC), value (float), approval, qualifier, ts_id."""
    rows = []
    for f in features:
        p = f.get("properties", {})
        try:
            v = float(p.get("value"))
        except (TypeError, ValueError):
            continue
        rows.append({
            "time": pd.Timestamp(p["time"]).tz_convert("UTC") if pd.Timestamp(p["time"]).tzinfo else pd.Timestamp(p["time"], tz="UTC"),
            "value": v,
            "unit": p.get("unit_of_measure"),
            "approval": p.get("approval_status"),
            "qualifier": p.get("qualifier"),
            "ts_id": p.get("time_series_id"),
            "site": p.get("monitoring_location_id"),
        })
    df = pd.DataFrame(rows, columns=["time", "value", "unit", "approval", "qualifier", "ts_id", "site"])
    if len(df):
        df = df.sort_values("time").drop_duplicates(subset=["time", "ts_id"]).reset_index(drop=True)
    return df


class NwisClient:
    def __init__(self, api_key: Optional[str] = None, timeout: float = 60.0):
        self.api_key = api_key or os.getenv("USGS_API_KEY") or None
        self._http = httpx.Client(timeout=timeout, headers={"User-Agent": "RiverSight/0.1"}, follow_redirects=True)

    def close(self) -> None:
        self._http.close()

    @retry(retry=retry_if_exception_type(_Transient), stop=stop_after_attempt(6),
           wait=wait_exponential(multiplier=1, min=2, max=60), reraise=True)
    def _get(self, url: str, params: Optional[dict] = None) -> dict:
        params = dict(params or {})
        if self.api_key:
            params["api_key"] = self.api_key
        r = self._http.get(url, params=params)
        check_rate_limit(r)
        r.raise_for_status()
        return r.json()

    def stage(self, nwis_id: str, start: datetime, end: datetime, parameter: str = PARAM_STAGE,
              chunk_days: int = 31, page_limit: int = 10000) -> pd.DataFrame:
        """Instantaneous values for a site in [start, end]. Walks chunks and pagination."""
        site = nwis_id if nwis_id.startswith("USGS-") else f"USGS-{nwis_id}"
        frames = []
        t = start
        while t < end:
            t2 = min(t + timedelta(days=chunk_days), end)
            url = f"{OGC_BASE}/collections/continuous/items"
            params = {"monitoring_location_id": site, "parameter_code": parameter,
                      "datetime": f"{_iso(t)}/{_iso(t2)}", "limit": page_limit, "f": "json"}
            while url:
                data = self._get(url, params)
                frames.append(features_to_frame(data.get("features", [])))
                nxt = next((l.get("href") for l in data.get("links", []) if l.get("rel") == "next"), None)
                url, params = (nxt, {}) if nxt else (None, None)
            t = t2
        if not frames:
            return features_to_frame([])
        df = pd.concat(frames, ignore_index=True)
        if len(df):
            df = df.sort_values("time").drop_duplicates(subset=["time", "ts_id"]).reset_index(drop=True)
            # If several time series exist (e.g., two sensors), keep the one with the most points.
            if df["ts_id"].nunique() > 1:
                keep = df["ts_id"].value_counts().idxmax()
                df = df[df["ts_id"] == keep].reset_index(drop=True)
        return df


LEGACY_IV = "https://waterservices.usgs.gov/nwis/iv/"


def parse_waterml_json(data: dict) -> dict[str, pd.DataFrame]:
    """Legacy NWIS IV WaterML-JSON → {site_no: DataFrame(time, value)}; keeps the longest series per site."""
    out: dict[str, pd.DataFrame] = {}
    for ts in data.get("value", {}).get("timeSeries", []):
        site = ts["sourceInfo"]["siteCode"][0]["value"]
        nodata = ts.get("variable", {}).get("noDataValue", -999999.0)
        for block in ts.get("values", []):
            rows = [(v["dateTime"], float(v["value"])) for v in block.get("value", [])
                    if v.get("value") not in (None, "") and float(v["value"]) != nodata]
            if not rows:
                continue
            df = pd.DataFrame(rows, columns=["time", "value"])
            df["time"] = pd.to_datetime(df["time"], utc=True, format="ISO8601")
            if site not in out or len(df) > len(out[site]):
                out[site] = df.sort_values("time").reset_index(drop=True)
    return out


def legacy_iv_multi(sites: list[str], start: datetime, end: datetime, parameter: str = PARAM_STAGE,
                    timeout: float = 180.0) -> dict[str, pd.DataFrame]:
    """Screening only: one request for many sites (legacy waterservices IV). Ground truth for
    evaluation still comes from the OGC API (NwisClient.stage)."""
    r = httpx.get(LEGACY_IV, params={"sites": ",".join(sites), "parameterCd": parameter, "startDT": _iso(start),
                                      "endDT": _iso(end), "format": "json", "siteStatus": "all"},
                  timeout=timeout, headers={"User-Agent": "RiverSight/0.1"})
    check_rate_limit(r)
    r.raise_for_status()
    return parse_waterml_json(r.json())
