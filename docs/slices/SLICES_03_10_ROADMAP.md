# Slices 03–10 — roadmap (contracts to be expanded by Cowork as each one approaches)

Dates assume SLICE_01 PASS on Oct 14. Each slice ends with `docs/STATUS.md` updated, results committed, tests green.

## SLICE 03 — Water-segmentation net + fused waterline (Oct 16–17)
- Pseudo-labels: SAM2 (5090, via workerq) prompted at transect waterline points that agree with the gauge-implied position (±2 px) → binary water masks; keep only frames with high agreement; manual spot check of 50.
- Train a small net (e.g. SegFormer-B0 or U-Net-MobileNet; ≤10 MB ONNX, 384×216 input) with leave-site-out validation; export ONNX opset 17; run in `cv2.dnn.readNetFromONNX(path, cv2.dnn.ENGINE_NEW)` with CLASSIC fallback; `max|cv2 − onnxruntime| ≤ 1e-3`; `getPerfProfile` table.
- Fused waterline: transect transition score × water-probability edge; report gain vs classical on dev sites.
- Acceptance: ≥10% MAE reduction or ≥10-pt coverage gain over classical at median site; latency table (new vs classic vs ORT) committed.

## SLICE 04 — Evaluation harness + frozen protocol (Oct 17–18)
- `scripts/eval.py` with splits (temporal, leave-site-out, few-shot N∈{3,5,10}); metrics (MAE, RMSE, %≤0.1, %≤0.25, coverage, NSE, rise P/R + lead time, false alerts/site-month); baselines (persistence, EfficientNet-B0 regression trained on the 5090, Canny/Hough + linear, isotonic lookup); ablations.
- Held-out: 1/3 of sites listed in `data/sites/heldout.yaml` and never processed until SLICE_08. `results/constants.sha256` of `src/riversight/constants.py`.
- Acceptance: one command reproduces the dev table from cached data; `results/dev_eval/` committed.

## SLICE 05 — AWS deploy (CDK) + dashboard (Oct 18–19) — needs Samuel's AWS account (docs/AWS_SETUP.md)
- CDK (Python): S3 (frames cache + static site), DynamoDB (readings, flags, agent traces), SQS, EventBridge 15-min rule, EC2 c8g.large ASG(1) from the COOL G4 AMI (SSM Marketplace alias, pinned version) running the worker as a systemd service in `/opt/cool/venvs/python_3.12`, CloudFront (Free plan) + WAF rate rule in front of S3 SPA + API (Lambda URL or the EC2 FastAPI via CloudFront origin), CloudWatch dashboard (public share), Budgets action (stop EC2 at $120), least-privilege roles.
- Worker asserts `cv2.__file__` starts with `/opt/cool` and exposes `/proof` (build info hash + signed instance identity document).
- Dashboard (web/): map of sites (Leaflet, inline), per-site page (live frame with transects + waterline, camera-vs-gauge chart, residual + flags, agent trace), `/judge` page (what to click, numbers, limitations).
- Acceptance: live URL; fleet loop running on all selected sites; alarms; `docs/DEPLOY.md` one-command deploy timed from fresh clone.

## SLICE 06 — Fleet agent + human approval (Oct 19–20)
- Strands Agents on Bedrock (Haiku 5.5; Nova 2 Lite fallback) — MCP server exposing read-only tools (`get_reading`, `get_frame`, `register_frame`, `detect_waterline`, `get_upstream`, `get_nwps_forecast`, `render_forecast_crest`) and side-effecting tools (`set_reference`, `quarantine`, `open_ticket`, `draft_alert`) behind an allow-list policy; Step Functions `waitForTaskToken` approval (SNS email + dashboard inbox) for `send_alert`.
- Four behaviors with traces: CAMERA_MOVED → re-anchor; LOW_CONF → better frame/neighbor/gauge fallback/ticket; GAUGE_SUSPECT → ticket; RISING → densify + upstream + NWPS + crest overlay + drafted alert → human.
- Fault-injection eval (≥30 episodes: shifted camera, occluded lens, gauge dropout, synthetic rise): task success, false-action rate, escalation rate, p50/p95 latency, $/episode; counterfactual "without OpenCV evidence".
- Acceptance: traces + eval CSV committed; kill switch + audit log demonstrated.

## SLICE 07 — COOL benchmark (Oct 19–20)
- Same c8g.large: arm A = COOL v3.1 venv; B1 = pip `opencv-python-headless==5.0.0.93`; B2 = pip 4.12.0.88; thread regimes (1 thread pinned; nproc threads; nproc procs × 1); 50 warmup + ≥300 iters; p50/p95/p99; fps; CPU%; $/1k frames incl. the COOL fee; break-even line; output equivalence (PSNR); per-stage Amdahl breakdown of our real per-frame pipeline; provenance (`getBuildInformation`, `cv2.__file__`, `uname -m`, instance identity doc, AMI id).
- Acceptance: `results/cool_bench/` CSV + `docs/COOL_BENCHMARK.md`; one-command repro; slowdowns reported if found.

## SLICE 08 — Held-out eval, flood replays, failure gallery (Oct 20–21)
- Freeze + hash constants → read held-out once; replay ≥2 real rise events through the full loop (agent included) from the archive; failure gallery with one paragraph each.
- Acceptance: `results/heldout/` committed; numbers copied verbatim into report.

## SLICE 09 — Report, diagrams, build guide (Oct 22–23)
- `report/REPORT.md` → PDF; `docs/ARCHITECTURE.md` (system + agent workflow diagrams, Mermaid + PNG); `docs/OPENCV5_USAGE.md`; `docs/RESPONSIBLE_USE.md`; `docs/PRIOR_ART.md` (from research); timed fresh-clone reproduction log.

## SLICE 10 — Video + Devpost + submit (Oct 24–25)
- Script by Cowork; recording by Samuel (face + narration) with screen capture; 3:00–3:30; demo in first 30 s; Devpost page fields; submit Oct 25; uptime monitor through Nov 10.
