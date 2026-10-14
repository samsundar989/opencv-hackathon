"""USGS NIMS (National Imagery Management System) client for HIVIS river cameras.

Verified endpoints (2026-10-13), see docs/DATA_SOURCES.md:
  GET https://api.waterdata.usgs.gov/nims/v0/cameras
  GET https://api.waterdata.usgs.gov/nims/v0/listFiles?camId=...&after=...&before=...&limit=...&recent=...
  GET https://usgs-nims-images.s3.amazonaws.com/{prefix}/{camId}/{filename}

Be gentle: this is a public-good service. Cache everything; never re-download.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

NIMS_BASE = "https://api.waterdata.usgs.gov/nims/v0"
S3_BASE = "https://usgs-nims-images.s3.amazonaws.com"

# Filename pattern: <camId>___<YYYY-MM-DD>T<HH-MM-SS>Z.jpg
_FNAME_RE = re.compile(r"^(?P<cam>.+?)___(?P<date>\d{4}-\d{2}-\d{2})T(?P<h>\d{2})-(?P<m>\d{2})-(?P<s>\d{2})Z\.(?P<ext>jpe?g|png)$", re.I)


@dataclass(frozen=True)
class Camera:
    cam_id: str
    nwis_id: Optional[str]
    name: str
    lat: Optional[float]
    lng: Optional[float]
    state: Optional[str]
    tz: Optional[str]
    created: Optional[datetime]
    newest_image: Optional[datetime]
    hidden: bool

    @property
    def gauged(self) -> bool:
        return bool(self.nwis_id) and bool(re.fullmatch(r"\d{8,15}", self.nwis_id or ""))

    def age_days(self, now: Optional[datetime] = None) -> Optional[float]:
        if not self.created:
            return None
        now = now or datetime.now(timezone.utc)
        return (now - self.created).total_seconds() / 86400

    def active(self, within_hours: float = 48, now: Optional[datetime] = None) -> bool:
        if not self.newest_image:
            return False
        now = now or datetime.now(timezone.utc)
        return (now - self.newest_image) <= timedelta(hours=within_hours)


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_float(s) -> Optional[float]:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def camera_from_record(rec: dict) -> Camera:
    """Build a Camera from a raw /cameras record (fields are strings)."""
    return Camera(
        cam_id=rec["camId"],
        nwis_id=(rec.get("nwisId") or "").strip() or None,
        name=rec.get("camName") or rec.get("camDesc") or rec["camId"],
        lat=_parse_float(rec.get("lat")),
        lng=_parse_float(rec.get("lng")),
        state=rec.get("stateAbrv"),
        tz=rec.get("tz"),
        created=_parse_dt(rec.get("createdDate")),
        newest_image=_parse_dt(rec.get("newestImageDT")),
        hidden=bool(rec.get("hideCam")),
    )


def parse_filename(filename: str) -> tuple[str, datetime]:
    """Return (cam_id, utc datetime) from a NIMS image filename.

    >>> parse_filename("TX_Guadalupe_Rv_at_Comfort___2026-10-10T11-41-21Z.jpg")[1].isoformat()
    '2026-10-10T11:41:21+00:00'
    """
    m = _FNAME_RE.match(filename)
    if not m:
        raise ValueError(f"unrecognized NIMS filename: {filename}")
    dt = datetime.fromisoformat(f"{m['date']}T{m['h']}:{m['m']}:{m['s']}+00:00")
    return m["cam"], dt


def image_url(cam_id: str, filename: str, prefix: str = "overlay") -> str:
    """S3 URL for an image. prefix: 'overlay' (full-res with USGS overlay text) or '720' (720-px)."""
    return f"{S3_BASE}/{prefix}/{cam_id}/{filename}"


class _Transient(Exception):
    pass


class NimsClient:
    """Small, polite client. One instance per process; reuse the HTTP connection."""

    def __init__(self, timeout: float = 30.0, user_agent: str = "RiverSight/0.1 (OpenCV AI Competition 2026)"):
        self._http = httpx.Client(timeout=timeout, headers={"User-Agent": user_agent}, follow_redirects=True)

    def close(self) -> None:
        self._http.close()

    @retry(retry=retry_if_exception_type(_Transient), stop=stop_after_attempt(5),
           wait=wait_exponential(multiplier=1, min=1, max=30), reraise=True)
    def _get(self, url: str, params: Optional[dict] = None) -> httpx.Response:
        r = self._http.get(url, params=params)
        if r.status_code == 429 and float(r.headers.get("retry-after", "0") or 0) > 90:
            from .nwis import RateLimited
            raise RateLimited(float(r.headers["retry-after"]))
        if r.status_code in (429, 500, 502, 503, 504):
            raise _Transient(f"{r.status_code} for {url}")
        r.raise_for_status()
        return r

    def cameras(self) -> list[Camera]:
        recs = self._get(f"{NIMS_BASE}/cameras").json()
        return [camera_from_record(r) for r in recs]

    def list_files(self, cam_id: str, after: Optional[datetime] = None, before: Optional[datetime] = None,
                   limit: int = 1000, recent: bool = True) -> list[str]:
        """Filenames for a camera in [after, before]. Newest first when recent=True."""
        params: dict = {"camId": cam_id, "limit": int(limit), "recent": "true" if recent else "false"}
        if after:
            params["after"] = after.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if before:
            params["before"] = before.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = self._get(f"{NIMS_BASE}/listFiles", params=params).json()
        if isinstance(data, dict):  # defensive: some deployments wrap arrays
            data = data.get("files") or data.get("items") or data.get("data") or []
        return [f for f in data if isinstance(f, str)]

    def list_files_range(self, cam_id: str, start: datetime, end: datetime, chunk_days: int = 7) -> list[str]:
        """Walk a long range in chunks so we never hit the 1000-item cap silently."""
        out: list[str] = []
        t = start
        while t < end:
            t2 = min(t + timedelta(days=chunk_days), end)
            files = self.list_files(cam_id, after=t, before=t2, limit=1000, recent=False)
            if len(files) >= 1000:  # chunk too big; split it
                mid = t + (t2 - t) / 2
                out += self.list_files_range(cam_id, t, mid, chunk_days)
                out += self.list_files_range(cam_id, mid, t2, chunk_days)
            else:
                out += files
            t = t2
        # dedupe, keep chronological order
        seen, uniq = set(), []
        for f in out:
            if f not in seen:
                seen.add(f)
                uniq.append(f)
        uniq.sort(key=lambda f: parse_filename(f)[1])
        return uniq

    @retry(retry=retry_if_exception_type(_Transient), stop=stop_after_attempt(5),
           wait=wait_exponential(multiplier=1, min=1, max=30), reraise=True)
    def download(self, cam_id: str, filename: str, dest_dir: Path, prefix: str = "720") -> Path:
        """Download one image into dest_dir/<prefix>/<cam_id>/<filename>; skip if cached."""
        dest = Path(dest_dir) / prefix / cam_id / filename
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = self._http.get(image_url(cam_id, filename, prefix))
        if r.status_code in (429, 500, 502, 503, 504):
            raise _Transient(f"{r.status_code} for {filename}")
        if r.status_code == 404 and prefix != "overlay":
            # 720 variant may be missing for some cameras; fall back to full-res
            return self.download(cam_id, filename, dest_dir, prefix="overlay")
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(r.content)
        tmp.replace(dest)
        return dest


def select_cameras(cams: Iterable[Camera], *, gauged: bool = True, active_hours: float = 48,
                   min_age_days: float = 90, states: Optional[set[str]] = None,
                   now: Optional[datetime] = None) -> list[Camera]:
    """Filter cameras for the fleet: visible, recently active, gauged, old enough to have history."""
    now = now or datetime.now(timezone.utc)
    out = []
    for c in cams:
        if c.hidden or not c.active(active_hours, now):
            continue
        if gauged and not c.gauged:
            continue
        age = c.age_days(now)
        if age is None or age < min_age_days:
            continue
        if states and (c.state or "").upper() not in states:
            continue
        out.append(c)
    return out
