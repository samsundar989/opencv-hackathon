"""Build the COOL benchmark input pack from the local frame cache (runs on the dev box, not on AWS).

The pack holds raw USGS frames, so it lives under the gitignored `data/` tree and only ever goes to the
project's private S3 bucket (non-negotiable 7). Layout:

  data/bench_pack/
    manifest.json        sites, per-site frame + homography for the kernel set, fleet frame list
    frames/<cam>/*.jpg   720 px NIMS frames, copied byte-for-byte from data/raw/720/
    models/sites/<cam>/  live site bundles (INTERFACES §1), copied from models/sites/
    models/onnx/*.onnx   ALIKED + LightGlue

Kernel set: per site, the daylight frame closest to --at that the registration cascade registers.
Fleet set: --fleet daylight frames drawn evenly from the 20 sites' cache (44 per site for 880), so the
880-frame run has the compute profile of one cycle over every gauged HIVIS camera, using our 20 models.

    python bench/make_pack.py --at 2026-10-13T18:00:00Z --fleet 880
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import cv2  # noqa: E402

from riversight.killtest import sun_elevation_deg  # noqa: E402
from riversight.vision.register import Registrar  # noqa: E402

RAW = ROOT / "data" / "raw" / "720"
SITES = ROOT / "models" / "sites"
ONNX = ROOT / "models" / "onnx"
ALIKED = ONNX / "aliked-n16rot-top1k-640.onnx"
LIGHTGLUE = ONNX / "aliked_lightglue.onnx"


def frame_time(p: Path) -> pd.Timestamp:
    """`<cam>___2026-10-13T18-00-03Z.jpg` → UTC timestamp."""
    s = p.stem.split("___")[1]
    d, t = s.split("T")
    return pd.Timestamp(f"{d}T{t.replace('-', ':')}")


def daylight_frames(cam: str, lat: float, lon: float, min_elev: float = 10.0) -> list[tuple[pd.Timestamp, Path]]:
    files = sorted((RAW / cam).glob("*.jpg"))
    if not files:
        return []
    ts = pd.Series([frame_time(f) for f in files])
    elev = sun_elevation_deg(lat, lon, ts)
    return [(t, f) for t, f, e in zip(ts, files, elev) if e >= min_elev]


def register_cascade(orb: Registrar, ali: Registrar | None, frame: np.ndarray):
    r = orb.register(frame)
    if r.ok or ali is None:
        return r
    return ali.register(frame)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", default="2026-10-13T18:00:00Z")
    ap.add_argument("--fleet", type=int, default=880)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "bench_pack")
    args = ap.parse_args()

    at = pd.Timestamp(args.at)
    cams = sorted(p.name for p in SITES.iterdir() if (p / "meta.json").exists())
    if args.out.exists():
        shutil.rmtree(args.out)
    (args.out / "frames").mkdir(parents=True)
    shutil.copytree(SITES, args.out / "models" / "sites")
    (args.out / "models" / "onnx").mkdir(parents=True)
    for f in (ALIKED, LIGHTGLUE):
        shutil.copy2(f, args.out / "models" / "onnx" / f.name)

    per_site = max(args.fleet // len(cams), 1)
    manifest = {"at": args.at, "sites": [], "fleet": []}
    for cam in cams:
        meta = json.loads((SITES / cam / "meta.json").read_text(encoding="utf-8"))
        ref = cv2.imread(str(SITES / cam / "reference.jpg"))
        orb = Registrar(use_aliked=False)
        orb.set_reference(ref)
        ali = Registrar(ALIKED, LIGHTGLUE)
        ali.set_reference(ref)
        day = daylight_frames(cam, meta["lat"], meta["lon"])
        if not day:
            print(f"{cam}: no cached daylight frames, skipped")
            continue
        (args.out / "frames" / cam).mkdir()
        chosen = None
        for t, f in sorted(day, key=lambda tf: abs((tf[0] - at).total_seconds()))[:40]:
            r = register_cascade(orb, ali, cv2.imread(str(f)))
            if r.ok:
                chosen = (t, f, r)
                break
        if chosen is None:
            print(f"{cam}: no registered daylight frame near {args.at}, skipped from kernel set")
        else:
            t, f, r = chosen
            shutil.copy2(f, args.out / "frames" / cam / f.name)
            manifest["sites"].append({"cam_id": cam, "frame": f"frames/{cam}/{f.name}", "t": str(t),
                                      "H": np.asarray(r.H, float).ravel().tolist(), "method": r.method,
                                      "ref_shape": meta["ref_shape"]})
        idx = np.linspace(0, len(day) - 1, min(per_site, len(day))).round().astype(int)
        for i in np.unique(idx):
            f = day[i][1]
            dst = args.out / "frames" / cam / f.name
            if not dst.exists():
                shutil.copy2(f, dst)
            manifest["fleet"].append({"cam_id": cam, "frame": f"frames/{cam}/{f.name}"})
        print(f"{cam}: kernel frame {'ok' if chosen else '—'}, fleet {len(np.unique(idx))}")

    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"pack: {len(manifest['sites'])} kernel sites, {len(manifest['fleet'])} fleet frames -> {args.out}")


if __name__ == "__main__":
    main()
