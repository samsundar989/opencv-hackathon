# SPRINT W1 — Cloud: live RiverSight on AWS Graviton (COOL) + judge-facing dashboard

**Owner:** Claude Code session "W1". **Commit prefix:** `[W1]`. **Status file:** `docs/status/W1.md`.
**Owns:** `infra/`, `src/riversight/live/`, `web/`, `scripts/export_site_models.py`, `scripts/deploy*`, `tests/w1/`.
**Read first:** `docs/PLAN_2026-10-22_FINAL_SPRINT.md`, `docs/INTERFACES.md`, `docs/decisions/D-0004_budget_cap.md`, `docs/decisions/D-0008_sprint_rulings.md`, CLAUDE.md (AWS section: new AWS experience, us-east-2 only).

## Gate G1 — Fri Oct 23 18:00 CT
A public CloudFront URL shows the 20 sites live, updated by a Graviton worker every 30 min.

## Steps

0. **Budget guard first (D-0004).** Nothing launches on EC2 until this exists and is verified.
   - A project-account Budget of $100 with alerts at 25/50/75/90% to samsundar989@gmail.com.
   - A stop-EC2 action at $90 (Budgets action or EventBridge→Lambda).
   - A CloudWatch billing alarm.
   - Record the ARNs in `docs/status/W1.md`.
   - Check `aws login --profile riversight` works. If it doesn't, write a `Q-` and work offline on steps 1–2 meanwhile.

1. **Site bundles.** `scripts/export_site_models.py` fits the D-0007 setting on all data up to now (history + Oct window + frames since Oct 14, fetched now) and writes `models/sites/<cam>/` per INTERFACES §1.
   - Include an extra-reference bank from the view-change segments found in history.
   - Unit test: a bundle round-trips and gives the same stage as `scene_score` on 10 frames.

2. **`riversight.live.cycle`.**
   - **Pipeline:**
     1. Newest NIMS frame per site, from the public `usgs-nims-images` bucket.
     2. Daylight test (solar elevation).
     3. Registration cascade: ORB → ALIKED+LightGlue → MAGSAC.
     4. Image-quality metrics.
     5. Scene model → stage ± σ, with Kalman state persisted per site.
     6. Gauge via OGC or IV.
     7. Flags (thresholds below).
     8. Wet overlay: draw blocks with h* ≤ estimated stage, semi-transparent blue, legend in ft.
     9. YuNet face blur.
     10. Write Reading JSON, overlay JPG and index per INTERFACES §2.
   - **Flag thresholds:**
     - `VIEW_CHANGE`: inlier ratio < 0.25 or reprojection error > 4 px
     - `LOW_QUALITY`: Laplacian variance or fog score beyond calibration p5
     - `GAUGE_STALE`: gauge age > 90 min
     - `DISAGREE`: |cam − gauge| > 2.5σ for 3 consecutive readings
     - `RISING`: camera or gauge stage up ≥ 0.5 ft in 3 h, or flood state ≥ elevated
   - **Agent hook:** for flagged readings, call `riversight.agent.handle()` (W2). If that fails, fall back to `riversight.agent.rules.handle()`. Until W2 lands, use a local stub with the same signature.
   - **Run modes:**
     - `--local` writes to `live_local/`.
     - `--s3` writes to the bucket.
     - `--replay <cam> <t0> <t1>` replays history; W2's eval uses this.
   - **Must run on Windows and on Graviton Linux.**
     - INTER_AREA only, because of KleidiCV issue #29794.
     - No `warpPerspective` with `BORDER_REPLICATE` on arm (#29816); use `BORDER_CONSTANT` and mask.

3. **Infra (CDK Python, `infra/`, us-east-2 only).**
   - **Storage:** S3 bucket (live data, models, site; private, with OAC).
   - **Front door:** CloudFront on the flat-rate Free plan if CDK supports it, otherwise the standard plan with a WAF rate rule. Origins: S3 for the SPA + `live/` JSON, and a Lambda Function URL (arm64, Python 3.14) for the approval API.
   - **Worker:** EC2 **m9g.large from the COOL G5 AMI**, subject to Samuel's Marketplace subscription. Until then, or if it fails, use Ubuntu 24.04 arm64 + pip `opencv-python-headless==5.0.0.93`.
     - systemd timer every 30 min.
     - Instance role least-privilege: S3 prefix, Bedrock InvokeModel on the `us.` Haiku profile, SNS publish, CloudWatch.
     - IMDSv2. No SSH; use SSM Session Manager.
   - **Alerts:** SNS topic, email subscription for Samuel only.
   - **Observability:** CloudWatch dashboard (cycle time, sites OK/flagged, agent decisions, cost) and alarms (no cycle in 75 min, error rate).
   - **COOL proof:** the worker asserts and records `cv2.__file__`, `cv2.__version__` and the `getBuildInformation()` hash, and serves `/proof.json` (also written to S3): AMI id, instance type, instance-identity document, build info, model SHAs.
   - **One command:** `python scripts/deploy.py` runs synth → deploy → upload models → smoke test → prints URL. Time it from a fresh clone and record the time.

4. **Dashboard (`web/`, static SPA, no build step or a tiny one; vanilla + Leaflet + Chart.js/uPlot from cdnjs; accessible, phone-friendly).**
   - **Home:**
     - Map plus a site list. Each site gets a status pill: OK / provisional (gauge down, camera-only) / quarantined / night.
     - A headline strip: "20 cameras · last cycle 12 min ago · 3 flagged".
   - **Site page:**
     - Latest frame with the wet-area overlay, plus a stage slider ("show what's under water at X ft"). The slider draws the h* map client-side from a PNG of h*. This is the money shot.
     - 7-day chart of camera ± σ vs gauge, with flags marked.
     - Flood-height map.
     - Agent decisions for this site.
     - Tier and frozen-test numbers for the site.
   - **`/judge`:**
     - 60-second tour: what to click.
     - Headline numbers copied from `results/kill_test_v2.md`, with links.
     - Agent eval and COOL numbers (from W2/W3 results files).
     - Failure cases.
     - Reproduce commands; links to the report, repo and video.
   - **`/approvals`:** pending agent actions. Approve/reject needs a token; the token goes to Samuel via SNS email, never into the repo.
   - **`/proof`:** pretty view of `proof.json`.

5. **Hardening (Sat).**
   - Uptime: CloudWatch synthetic check or an alarm on stale `index.json`.
   - Costs in `docs/status/W1.md`.
   - `docs/DEPLOY.md` written with W3.
   - Tear-down command documented: stop after Nov 10.

## Acceptance
- [ ] Budget guard live and verified before the first EC2 launch (ARNs in status).
- [ ] 20 bundles exported; local cycle runs all 20 sites; tests green.
- [ ] G1: live URL with all 20 sites updating every 30 min for ≥ 6 h without manual help.
- [ ] `proof.json` shows COOL (or a documented fallback).
- [ ] `/judge`, `/approvals`, `/proof` pages work on desktop and phone.
- [ ] `scripts/deploy.py` fresh-clone deploy timed; `docs/DEPLOY.md`.
- [ ] Spend to date reported; projected spend through Nov 10 ≤ $60.
