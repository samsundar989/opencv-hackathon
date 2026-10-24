"""'Replay a flood' assets for the site pages (D-0013 W1-2).

Runs W2's three out-of-sample flood replays (scripts/agent_replay.EVENTS: bundles cut 2–3 days before each rise)
through W1's live per-site step (`riversight.live.cycle.replay`), with the deterministic rules agent, and writes a
frame-by-frame manifest: blurred overlay thumbnail (connected inundation at the camera's stage), camera ± σ /
lower bound, gauge, flags, status and the agent's actions + rationale as they happened.

  build  (heavy: ALIKED registration over ~150 frames → worker-q)
    workerq submit --project riversight --priority high --gpus 0 --ram 5 --cpus 2 --node local -- \
      <python> scripts/deploy_replays.py build --out C:/Users/samsu/Documents/opencv-hackathon/live_local/replays
  upload (light)
    python scripts/deploy_replays.py upload       → s3://<bucket>/site/replays/<event>/ + site/replays/index.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "live_local" / "replays"


def event_id(cam: str, t0: str) -> str:
    return f"{cam}__{t0[:10]}"


def build(out: Path):
    import agent_replay as W2                                 # W2's events + agent function (read-only reuse)
    from riversight.live import cycle
    index = []
    for cam, cut, t0, t1 in W2.EVENTS:
        eid = event_id(cam, t0)
        store_dir = out / eid
        bundles = ROOT / "data" / "derived" / "agent_bundles_replay" / cut
        os.environ["RIVERSIGHT_LIVE_DIR"] = str(store_dir)    # the agent's tools read W1's frames from here
        os.environ["RIVERSIGHT_AGENT_ISOLATE"] = "0"
        rows = cycle.replay(cam, t0, t1, store_dir, W2.make_agent_fn(cam, bundles, store_dir, False), bundles)
        frames = [{"t": r["t_frame"], "thumb": r.get("thumb_key"), "overlay": r["overlay_key"],
                   "camera_ft": r.get("camera_stage_ft"), "camera_at_least_ft": r.get("camera_at_least_ft"),
                   "sigma_ft": r.get("camera_sigma_ft"), "gauge_ft": r.get("gauge_stage_ft"), "flags": r["flags"],
                   "status": r.get("status"), "daylight": r["daylight"], "flood_state": r.get("flood_state"),
                   "agent": r.get("agent")} for r in rows]
        meta = json.loads((bundles / cam / "meta.json").read_text(encoding="utf-8"))
        man = {"event": eid, "cam_id": cam, "bundle_cut": cut, "window": [t0, t1], "policy": "rules (no LLM)",
               "calibrated_range_ft": [meta["stage_min"], meta["stage_max"]], "n_frames": len(frames),
               "note": "out-of-sample: the camera's model was trained only on frames before the bundle cut",
               "frames": frames}
        (store_dir / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
        index.append({k: man[k] for k in ("event", "cam_id", "bundle_cut", "window", "n_frames", "calibrated_range_ft")})
        print(f"{eid}: {len(frames)} frames", flush=True)
    (out / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")


def upload(out: Path, profile: str):
    import boto3
    sys.path.insert(0, str(ROOT / "scripts"))
    from deploy import outputs, session
    o = outputs()
    s3 = session(profile).client("s3")
    n = 0
    for man_p in out.glob("*/manifest.json"):
        d = man_p.parent
        man = json.loads(man_p.read_text(encoding="utf-8"))
        for f in man["frames"]:
            for k in ("thumb", "overlay"):
                if f.get(k):
                    s3.put_object(Bucket=o["BucketName"], Key=f"site/replays/{man['event']}/{f[k]}",
                                  Body=(d / f[k]).read_bytes(), ContentType="image/jpeg", CacheControl="max-age=86400")
                    n += 1
        s3.put_object(Bucket=o["BucketName"], Key=f"site/replays/{man['event']}/manifest.json",
                      Body=man_p.read_bytes(), ContentType="application/json", CacheControl="no-cache")
    s3.put_object(Bucket=o["BucketName"], Key="site/replays/index.json", Body=(out / "index.json").read_bytes(),
                  ContentType="application/json", CacheControl="no-cache")
    print(f"uploaded {n} images + manifests")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "upload"])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--profile", default="riversight")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    build(a.out) if a.cmd == "build" else upload(a.out, a.profile)


if __name__ == "__main__":
    main()
