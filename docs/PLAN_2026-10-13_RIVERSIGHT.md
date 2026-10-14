# PLAN 2026-10-13 — RiverSight (plan of record)

Author: Cowork (strategist). Executor: Claude Code (builder). Owner: Samuel.
Status: **ACTIVE**. Supersedes nothing (first plan). Changes are made by a new `PLAN_<date>_*.md` or a `D-NNNN` ruling in `docs/DECISIONS.md`.

## 1. Goal and success criteria
- **Goal:** 1st overall in the OpenCV AI Competition 2026 (+ COOL and Agentic specials if cheap). Secondary: a public benchmark + toolkit with life after the competition.
- **Submission (Sun Oct 25, 2026):** live endpoint (map + per-site view + `/judge` page + `/proof`), technical report, architecture + agent diagrams, repo with pinned deps and one-command build/deploy/test, ≤3:30 video with Samuel on camera, `results/` with held-out evaluation, failure gallery, COOL benchmark, agent evaluation.
- **Hard constraints:** OpenCV 5.0.0.93 pinned; OpenCV does load-bearing work; a meaningful AWS component (Graviton EC2 + COOL worker, CloudFront front door, Bedrock agent, Step Functions approvals); honest numbers; privacy blur; no raw-image redistribution.

## 2. Scope (13 days → cut hard)
**In:** stage (water level) only; 30–60 sites; one agent with four behaviors; one dashboard; COOL 3-arm benchmark; held-out eval; report + video.
**Out (unless everything else is done by Oct 21):** discharge/LSPIV, C++ hot path, drone footage, ungauged-site transfer, multi-camera triangulation, in-DNN VLM.

## 3. System design
```
EventBridge (15 min) → SQS → Graviton worker (c8g.large, COOL AMI)
  for each site:
    1. fetch newest 720-px frame (NIMS listFiles + S3 GET), mask overlay text
    2. REGISTER: ALIKED keypoints → LightGlueMatcher vs site reference bank (2–6 refs chosen by ANNIndex on a cheap global descriptor) → USAC_MAGSAC homography H, inlier count, reprojection error  → registration score
    3. WATERLINE: warp frame by H into reference coords (warpPerspective, 5.x fast path); along K fixed transects (polylines drawn once per site in reference coords) build 1-D profiles: grayscale, Sobel/Scharr gradient, HSV, local texture (Laplacian var), optional water-probability from the ONNX seg net; detect the dominant land→water transition → waterline coordinate s_k (pixels along transect) + confidence
    4. STAGE: per transect, projective model u(h)=(a·h+b)/(c·h+1) fitted from history (gauge stage ↔ s_k) → invert to h_k; fuse transects (weighted median) → ĥ ± σ
    5. QA: residual r = ĥ − gauge (when gauge present); CUSUM on r; flags: CAMERA_MOVED (low reg score), OCCLUDED/LOW_CONF, GAUGE_SUSPECT (persistent |r| with high confidence), RISING (dĥ/dt > threshold)
  write reading + flags to DynamoDB/S3; publish metrics (CloudWatch, dimension backend=cool|stock)
Agent (Strands on Bedrock Haiku 5.5; MCP tools = our OpenCV functions + data fetchers + action tools)
  triggers on flags; actions: re-anchor (new reference), quarantine, fetch full-res/next/neighbor frame, open ticket, check upstream sites + NWPS forecast, render forecast crest into frame (inverse model), draft alert → Step Functions waitForTaskToken → human approves → SNS
Dashboard (S3 + CloudFront Free plan + WAF): map of sites; per-site: live frame w/ transects+waterline, camera-vs-gauge chart, residual, flags, agent trace; /judge page; /proof (COOL build info + instance identity)
Batch/eval (local 5090 + CPU): dataset builder, pseudo-labels (SAM2), seg training → ONNX, eval harness, COOL benchmark runner
```
**Why this is "OpenCV 5" and not "OpenCV":** ALIKED/LightGlue (`features`, 5.0-only), USAC_MAGSAC default robust estimators, new DNN engine (`ENGINE_NEW`) running our ONNX seg net with `getPerfProfile`, `ANNIndex` reference bank, 5.x fast warps, `FontFace` Unicode overlays, `calib`-module undistortion where lens distortion is visible. Document each in `docs/OPENCV5_USAGE.md`.

## 4. Slices (contracts in `docs/slices/`)
| # | Slice | Window | Acceptance (summary) |
|---|---|---|---|
| 01 | Ingest + site selection + **kill test** | Oct 13–14 | 20 sites × 30 days fetched & joined; classical waterline + projective fit; **PASS = registration ≥90% frames AND MAE ≤0.25 ft at ≥10 sites** (temporal split 20/10 days). Report `results/kill_test.md`. |
| 02 | Registration + transects + stage model v1 | Oct 15–16 | ALIKED/LightGlue/MAGSAC registration with score; transect tool; projective + isotonic baselines; per-site MAE table on 30–60 sites × 60–90 days; ORB/AKAZE ablation. |
| 03 | Water-seg net + fused waterline | Oct 16–17 | SAM2 pseudo-labels (5090) → small seg net (e.g., U-Net/SegFormer-tiny) → ONNX → cv2.dnn new engine; cv2.dnn vs onnxruntime max-abs-diff ≤1e-3; ≥10% MAE improvement or coverage gain over classical on the dev set; latency table (new vs classic vs ORT). |
| 04 | Eval harness + frozen protocol | Oct 17–18 | `scripts/eval.py`: temporal split, leave-site-out, few-shot onboarding (3/5/10 points); metrics MAE/RMSE, %≤0.1/0.25 ft, coverage, NSE, rise P/R + lead time, false alerts/site-month; baselines (persistence, EfficientNet-B0 regression, Canny/Hough); `results/constants.sha256`; held-out set untouched until Oct 21. |
| 05 | AWS deploy (CDK) + dashboard | Oct 18–19 | c8g.large on COOL G4 AMI behind CloudFront; EventBridge→SQS→worker loop live on all selected sites; DynamoDB readings; SPA dashboard; `/judge`, `/proof`; Budgets alarms; WAF rate rule; logs/metrics dashboard shared. |
| 06 | Fleet agent + human approval | Oct 19–20 | Strands agent on Bedrock; MCP tool catalog (read-only vs side-effecting); Cedar/allow-list policy; Step Functions approval; 4 behaviors demonstrated with traces; fault-injection eval (≥30 episodes): success rate, false-action rate, escalation rate, $/episode. |
| 07 | COOL benchmark | Oct 19–20 | Same c8g.large: COOL v3.1 vs pip 5.0.0.93 vs pip 4.12; thread regimes; p50/p95, fps, $/1k frames, break-even; proof artifacts (`getBuildInformation`, `cv2.__file__`, signed instance identity). Report slowdowns honestly. |
| 08 | Held-out eval + flood replays + failure gallery | Oct 20–21 | Constants frozen & hashed → one read of held-out; ≥2 real rise events replayed through agent; failure gallery (night, fog, glare, ice, vegetation, flat bank, wake). |
| 09 | Report, diagrams, build guide, OpenCV5 table, responsible use, prior art | Oct 22–23 | `report/REPORT.md` (+PDF), `docs/ARCHITECTURE.md` with diagrams, `docs/OPENCV5_USAGE.md`, `docs/RESPONSIBLE_USE.md`, reproducible one-command run documented and timed from a fresh clone. |
| 10 | Video + Devpost + submit | Oct 24–25 | 3:00–3:30 video (demo in first 30 s; Samuel on camera); Devpost page; submit Oct 25; endpoint monitoring through Nov 10. |

## 5. Evaluation protocol (decided now; details in SLICE_04)
- Units: feet (USGS native). Primary metric: MAE per site, median across sites; secondary: % within ±0.1 ft and ±0.25 ft; coverage (% of frames yielding a reading with confidence ≥ threshold).
- Splits: (a) temporal: fit on the first 2/3 of each site's window, test on the last 1/3; (b) leave-site-out for the seg net and any cross-site components; (c) few-shot onboarding: calibrate on N∈{3,5,10} gauge points, test on the rest.
- Baselines: persistence (last gauge value), EfficientNet-B0 regression from the full frame (USGS's own approach; train on the 5090), Canny/Hough waterline + linear fit, isotonic lookup (ours, non-physics).
- Ablations: no registration; linear instead of projective; ORB/AKAZE instead of ALIKED/LightGlue; classical-only vs fused waterline.
- Held-out: 1/3 of sites never used for any tuning; read once on Oct 21 with hashed constants.

## 6. Risks and kill criteria
- **Signal too weak (wide rivers, few px/ft):** site selection scores px/ft from history; report coverage honestly. Kill test decides by Oct 14 night.
- **Registration fails under lighting/season change:** reference bank per site (day/dusk/season) chosen via ANNIndex; fall back to ECC/phaseCorrelate; report.
- **Daylight-only cameras:** state it; night = gauge fallback.
- **AWS account friction (Free plan, quotas, Bedrock access):** Samuel does `docs/AWS_SETUP.md` on Oct 13–14; everything in slices 01–04 runs locally and does not block on AWS.
- **Time:** every slice has a "ship with less" line in its contract. The demo must work end-to-end by Oct 21 even if ugly.

## 7. Division of labor
- **Samuel:** AWS account + setup (`docs/AWS_SETUP.md`), Slack, Devpost project, approvals in `docs/HUMAN.md`, video appearance, final submit.
- **Claude Code (Opus):** everything in `docs/slices/`, status in `docs/STATUS.md`, decisions in `docs/DECISIONS.md`.
- **Cowork (Fable):** plan/slice contracts, research, review of results, report/video script, Devpost text, competitor watch.
