"""RiverSight command line.

  riversight cameras   --active --gauged --min-age-days 90 [--state TX] [--out data/cameras.csv]
  riversight fetch     --site <camId> --days 30 [--prefix 720]
  riversight kill-test --sites data/sites/kill_test.yaml --days 30   (SLICE_01; see docs/slices)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich import print as rprint
from rich.table import Table

app = typer.Typer(no_args_is_help=True, add_completion=False)
DATA = Path(os.getenv("RIVERSIGHT_DATA", "data"))


@app.callback()
def _init():
    load_dotenv()


@app.command()
def cameras(active: bool = True, gauged: bool = True, min_age_days: float = 90, state: Optional[str] = None,
            out: Optional[Path] = None, limit: int = 50):
    """List HIVIS cameras that pass the fleet filter."""
    from riversight.data.nims import NimsClient, select_cameras
    import pandas as pd

    c = NimsClient()
    cams = c.cameras()
    sel = select_cameras(cams, gauged=gauged, active_hours=48 if active else 1e9, min_age_days=min_age_days,
                         states={state.upper()} if state else None)
    rprint(f"[bold]{len(cams)}[/bold] cameras total, [bold]{len(sel)}[/bold] selected")
    rows = [{"cam_id": x.cam_id, "nwis_id": x.nwis_id, "state": x.state, "name": x.name,
             "created": x.created, "newest": x.newest_image, "lat": x.lat, "lng": x.lng} for x in sel]
    df = pd.DataFrame(rows)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        rprint(f"wrote {out}")
    t = Table("cam_id", "nwis", "state", "created", "newest")
    for r in rows[:limit]:
        t.add_row(r["cam_id"], str(r["nwis_id"]), str(r["state"]), str(r["created"])[:10], str(r["newest"])[:16])
    rprint(t)


@app.command()
def fetch(site: str, days: int = 30, end: Optional[str] = None, prefix: str = "720", max_images: int = 5000,
          with_gauge: bool = True):
    """Download images + gauge readings for one camera into data/raw and data/derived."""
    from riversight.data.nims import NimsClient
    from riversight.data.nwis import NwisClient
    from riversight.data.join import frames_table, join_frames_to_stage

    end_dt = datetime.fromisoformat(end).replace(tzinfo=timezone.utc) if end else datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)
    nims = NimsClient()
    cams = {c.cam_id: c for c in nims.cameras()}
    if site not in cams:
        raise typer.BadParameter(f"unknown camId {site}")
    cam = cams[site]
    files = nims.list_files_range(site, start_dt, end_dt)
    rprint(f"{site}: {len(files)} images between {start_dt:%Y-%m-%d} and {end_dt:%Y-%m-%d}")
    files = files[-max_images:]
    raw = DATA / "raw"
    for i, f in enumerate(files, 1):
        nims.download(site, f, raw, prefix=prefix)
        if i % 100 == 0:
            rprint(f"  {i}/{len(files)}")
    frames = frames_table(files)
    frames["path"] = [str(raw / prefix / site / f) for f in frames["filename"]]
    if with_gauge and cam.gauged:
        stage = NwisClient().stage(cam.nwis_id, start_dt - timedelta(hours=1), end_dt + timedelta(hours=1))
        rprint(f"gauge {cam.nwis_id}: {len(stage)} readings")
        joined = join_frames_to_stage(frames, stage)
        joined["path"] = frames["path"].values
        frames = joined
        derived = DATA / "derived" / site
        derived.mkdir(parents=True, exist_ok=True)
        stage.to_parquet(derived / "stage.parquet", index=False)
    derived = DATA / "derived" / site
    derived.mkdir(parents=True, exist_ok=True)
    frames.to_parquet(derived / "frames.parquet", index=False)
    rprint(f"wrote {derived/'frames.parquet'} ({len(frames)} rows, {frames['stage_ft'].notna().sum() if 'stage_ft' in frames else 0} with stage)")


@app.command("kill-test")
def kill_test(sites: Path = Path("data/sites/kill_test.yaml"), days: int = 30):
    """SLICE_01 kill test. Implemented by Claude Code per docs/slices/SLICE_01_INGEST_KILL_TEST.md."""
    raise typer.Exit(code=typer.echo("kill-test is implemented in SLICE_01 — see docs/slices/SLICE_01_INGEST_KILL_TEST.md", err=True) or 2)


if __name__ == "__main__":
    app()
