#!/usr/bin/env python3
"""RiverSight CDK app (us-east-2 only; new AWS experience, D-0003).

  cdk deploy RiverSightGuard     budget guard (D-0004) — always first, verified before any EC2 launch
  cdk deploy RiverSightLive      bucket, CloudFront, approvals API, Graviton worker, alarms

Context (cdk.json, override with -c): worker_ami=ubuntu|cool, cool_ami_id, worker_instance_type,
approval_token_sha256 (set by scripts/deploy.py; the token itself never touches the repo).
"""
import os

import aws_cdk as cdk

from stacks.guard import GuardStack
from stacks.live import LiveStack

app = cdk.App()
ctx = app.node.try_get_context
region = ctx("region") or "us-east-2"
if region != "us-east-2":
    raise SystemExit("RiverSight resources live in us-east-2 only (D-0003)")
env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=region)
email = ctx("alert_email")

GuardStack(app, "RiverSightGuard", env=env, email=email, budget_usd=float(ctx("budget_usd")),
           stop_pct=float(ctx("stop_at_pct")), description="RiverSight D-0004 budget guard ($100 cap, stop EC2 at 90%)")
if ctx("deploy_live") != "0":
    LiveStack(app, "RiverSightLive", env=env, email=email, worker_ami=ctx("worker_ami"),
              instance_type=ctx("worker_instance_type"), bedrock_profile=ctx("bedrock_profile"),
              approval_token_sha256=ctx("approval_token_sha256") or "", cool_ami_id=ctx("cool_ami_id") or "",
              origin_secret=ctx("origin_secret") or "",
              description="RiverSight live: S3 + CloudFront + approvals API + Graviton worker")
app.synth()
