# Deploying RiverSight on AWS

**Scope:** all resources live in **us-east-2**, the project's assigned Region (D-0003). Infrastructure is CDK Python (`infra/`), and one command (`scripts/deploy.py`) deploys it.

## Prerequisites
- Python ≥ 3.12 with `pip install -e ".[dev,aws]"`.
- Node 22 and `npm install -g aws-cdk`.
- AWS credentials: `aws login --profile riversight`, which opens a browser sign-in. Check them with `aws sts get-caller-identity --profile riversight`.
- Bootstrap CDK once per project: `cd infra && cdk bootstrap --profile riversight`.
- Local model bundles: `python scripts/export_site_models.py`. This needs the data cache; see `docs/REPRODUCE.md`.
- Optional, for the COOL worker: accept the Marketplace terms for `prodview-igdweaoo6prb6` (COOL Graviton5).

## 1. Budget guard first (D-0004)
```
python scripts/deploy.py --guard-only
```
This creates:
- **Budget `riversight-cap`**: $100 of gross cost (credits excluded), cumulative from 2026-10-01. Emails at 25/50/75% actual and 100% forecast.
- **Stop action at 90% actual:** the budget notifies SNS `riversight-stop`, which triggers Lambda `riversight-budget-stop-ec2`. The Lambda stops every running instance tagged `Project=riversight`. It stops them and never terminates them.

The script then prints the budget's ARN, limit and notifications. A full deploy runs this verification again and refuses to continue if the budget is missing.

CloudWatch's billing metric exists only in us-east-1, which this project cannot use for alarms. The 100%-forecast notification is the backup alert instead.

## 2. Full deploy
```
python scripts/deploy.py                                     # stock Ubuntu 24.04 arm64 + pip opencv 5.0.0.93
python scripts/deploy.py --worker-ami cool --cool-ami-id ami-… --instance-type m9g.medium   # COOL G5
```
The script runs these steps in order:
1. Verifies the guard.
2. `cdk deploy --all`.
3. Uploads the worker tarball (`src/`, `models/sites/`, the ONNX models) to `s3://<bucket>/deploy/`.
4. Uploads `web/` and the site data built from committed `results/` to `site/`, then invalidates CloudFront.
5. Emails the approval token once. The token is stored only in your gitignored `.env` as `APPROVAL_TOKEN`; the Lambda holds its sha256.
6. Tells the worker over SSM to pull the new tarball.
7. Waits for a fresh `live/index.json` behind CloudFront.

It prints the URL and the total time when it finishes.

Partial updates:
- `--site-only`: dashboard and site data.
- `--code-only`: worker code and models.

## What runs
| piece | where | notes |
|---|---|---|
| dashboard | S3 `site/` behind CloudFront (OAC) | static, no build step |
| live data | S3 `live/` behind CloudFront `/live/*` (60 s TTL) | readings, overlays (face-blurred), index, agent log, approvals, `proof.json` |
| approvals API | Lambda Function URL behind CloudFront `/api/*` | approve or reject needs the token |
| worker | EC2 Graviton (default `c8g.medium`); IMDSv2; no SSH (SSM Session Manager) | systemd timer every 15 min; each site every 30 min, or 15 min while the agent has it on DENSIFY |
| alerts | SNS `riversight-alerts` (email) | approvals, alarms |
| monitoring | CloudWatch dashboard `riversight`; alarms `riversight-no-cycle-75min`, `riversight-cycle-errors` | metrics namespace `RiverSight` |

To get a shell on the worker:
```
aws ssm start-session --profile riversight --target <WorkerInstanceId>
```
Logs come from `journalctl -u riversight-cycle`.

## Local preview (no AWS)
```
python -m riversight.live.cycle --local      # one live cycle into live_local/
python scripts/deploy_preview.py             # http://localhost:8765/
```

## Tear-down (after judging ends Nov 9; the stack stays up until then)
```
cd infra
cdk destroy RiverSightLive --profile riversight   # the S3 bucket is retained (RETAIN); empty and delete it by hand
cdk destroy RiverSightGuard --profile riversight  # last, so the guard outlives everything that costs money
```
