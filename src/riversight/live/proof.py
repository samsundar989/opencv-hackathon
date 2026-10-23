"""Runtime evidence (SPRINT W1 step 3, COOL proof) and CloudWatch metrics for the live worker.

`proof()` records which OpenCV build actually runs (cv2.__file__, __version__, sha256 of
getBuildInformation(), the optimisation lines from it), the EC2 instance-identity document and AMI id
(IMDSv2), and the model SHAs. The worker writes it to live/proof.json every cycle; the dashboard's
/proof page renders it.
"""
from __future__ import annotations

import hashlib
import os
import platform
from datetime import datetime, timezone

import cv2

IMDS = "http://169.254.169.254/latest"


def _imds() -> dict:
    try:
        import httpx
        tok = httpx.put(f"{IMDS}/api/token", headers={"X-aws-ec2-metadata-token-ttl-seconds": "300"}, timeout=1).text
        h = {"X-aws-ec2-metadata-token": tok}
        doc = httpx.get(f"{IMDS}/dynamic/instance-identity/document", headers=h, timeout=1).json()
        return {"instance_identity": {k: doc.get(k) for k in ("instanceId", "instanceType", "imageId", "region",
                                                              "availabilityZone", "architecture", "pendingTime")}}
    except Exception:
        return {"instance_identity": None}


def build_summary() -> dict:
    info = cv2.getBuildInformation()
    keep = [ln.strip() for ln in info.splitlines()
            if any(k in ln for k in ("Version control", "KleidiCV", "Baseline", "Dispatched", "Parallel framework",
                                     "Platform:", "Host:", "CPU/HW features", "NEON", "SVE", "COOL", "Extra modules"))]
    return {"version": cv2.__version__, "file": cv2.__file__,
            "build_info_sha256": hashlib.sha256(info.encode()).hexdigest(), "build_info_excerpt": keep[:40],
            "cool": "/opt/cool/" in cv2.__file__ or "COOL" in info,
            "dnn_engines": [n for n in dir(cv2.dnn) if n.startswith("ENGINE_")]}


def proof(models: list) -> dict:
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(), "machine": platform.machine(), "platform": platform.platform(),
        "ami_kind": os.environ.get("RIVERSIGHT_AMI_KIND", "local"), "opencv": build_summary(), **_imds(),
        "models": [{"cam_id": m.cam_id, "model_sha": m.meta["model_sha"], "frozen_config_sha": m.meta["frozen_config_sha"],
                    "trained_at": m.meta["trained_at"], "n_calib_frames": m.meta["n_calib_frames"]} for m in models],
        "code_sha": os.environ.get("RIVERSIGHT_CODE_SHA", "unknown"),
    }


def put_metrics(idx: dict, decisions: list[dict]) -> None:
    """Cycle metrics → CloudWatch namespace RiverSight (worker only: RIVERSIGHT_METRICS=1)."""
    if os.environ.get("RIVERSIGHT_METRICS") != "1":
        return
    import boto3
    llm = sum(1 for d in decisions if d.get("decided_by") == "llm")
    data = [("CycleCompleted", 1, "Count"), ("CycleSeconds", idx["cycle_ms"] / 1000, "Seconds"),
            ("SitesOk", idx["n_ok"], "Count"), ("SitesFlagged", idx["n_flagged"], "Count"),
            ("SiteErrors", idx["n_errors"], "Count"), ("AgentLLM", llm, "Count"),
            ("AgentRules", len(decisions) - llm, "Count"),
            ("AgentTokens", sum((d.get("tokens_in") or 0) + (d.get("tokens_out") or 0) for d in decisions), "Count")]
    try:
        boto3.client("cloudwatch").put_metric_data(
            Namespace="RiverSight", MetricData=[{"MetricName": n, "Value": float(v), "Unit": u} for n, v, u in data])
    except Exception as e:
        print(f"put_metric_data failed: {e!r}", flush=True)
