"""W4 (D-0014 W4-1): build the recalibration base sets, the exact training data of the served v2 bundles.

  python scripts/v2_recal_base.py                 → data/derived/<cam>/recal_base.npz (t ns, h, F f16, P f16)
  python scripts/v2_recal_base.py --cut 2026-10-03  base without Oct 3–14 (used only by the end-to-end test
                                                   that replays those frames as "logged" readings)
  python scripts/v2_recal_base.py --upload <bucket> also put each base to s3://<bucket>/models/recal_base/<cam>.npz
                                                   (profile riversight; ~2.5 GB total, < $0.10/month)

Run through worker-q (~4 GB RAM per site at most):
  workerq submit --project riversight --gpus 0 --ram 6 --cpus 2 -- python scripts/v2_recal_base.py
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
DATA = Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))


def build(cam: str, cut: pd.Timestamp | None) -> tuple[Path, int]:
    from v2_export_bundles import training_set
    t, h, F, P, _ = training_set(cam, cut)
    name = "recal_base.npz" if cut is None else f"recal_base_cut{cut:%Y%m%d}.npz"
    out = DATA / "derived" / cam / name
    b = io.BytesIO()
    np.savez_compressed(b, t=pd.DatetimeIndex(t).as_unit("ns").asi8, h=np.asarray(h, float),
                        F=np.asarray(F, np.float16), P=np.asarray(P, np.float16))
    out.write_bytes(b.getvalue())
    return out, len(t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundles", type=Path, default=ROOT / "models" / "sites_v2")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--cut")
    ap.add_argument("--upload", help="S3 bucket (only for full, uncut bases)")
    a = ap.parse_args()
    cut = pd.Timestamp(a.cut, tz="UTC") if a.cut else None
    cams = sorted(p.name for p in a.bundles.iterdir() if p.is_dir() and (not a.only or p.name in a.only))
    s3 = None
    if a.upload:
        if cut is not None:
            sys.exit("--upload is only for full bases")
        import boto3
        s3 = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "riversight")).client("s3")
    for i, cam in enumerate(cams):
        p, n = build(cam, cut)
        msg = f"{cam}: {n} frames, {p.stat().st_size / 1e6:.0f} MB"
        if s3 is not None:
            s3.upload_file(str(p), a.upload, f"models/recal_base/{cam}.npz")
            msg += " uploaded"
        print(msg, flush=True)
        prog = os.environ.get("WORKERQ_PROGRESS")
        if prog:
            Path(prog).write_text(f"{(i + 1) / len(cams):.4f}")


if __name__ == "__main__":
    main()
