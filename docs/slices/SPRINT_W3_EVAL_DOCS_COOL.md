# SPRINT W3 — COOL benchmark, report, docs, reproducibility

**Owner:** Claude Code session "W3". **Commit prefix:** `[W3]`. **Status file:** `docs/status/W3.md`.
**Owns:** `bench/`, `results/cool_bench/`, `report/`, `docs/{ARCHITECTURE,OPENCV5_USAGE,RESPONSIBLE_USE,PRIOR_ART,COOL_BENCHMARK,REPRODUCE,DEPLOY}.md` (DEPLOY together with W1), `README.md`, and the "What we are building" paragraph of `CLAUDE.md`. Tests go in `tests/w3/`.
**Read first:**
- `docs/PLAN_2026-10-22_FINAL_SPRINT.md`
- `results/kill_test_v2.md`
- D-0002, D-0006, D-0007
- `docs/research/*` (prior art, judges, COOL)

## 1. Refresh the descriptions first (Thu)
`CLAUDE.md` "What we are building" and `README.md` still describe the old transect/projective design. Rewrite both around the scene model and flood-height map, live fleet, River Steward agent and COOL on Graviton5.

The README is the judges' front door:
- one-paragraph pitch
- live URL (placeholder until G1)
- 3 headline numbers with links to results files
- architecture image
- quick start
- repo map
- honest limitations

## 2. COOL benchmark (Fri–Sat) — Best Use of COOL prize
- **Arms on the same m9g.large** (short-lived bench instance launched from the COOL G5 AMI; the script terminates it):
  - **A** — COOL Python 3.14 venv
  - **B** — pip `opencv-python-headless==5.0.0.93` in a clean venv on the same instance
  - **C** (optional) — pip 4.12 / 4.14.0.94, for comparison with the vendor's numbers
- **Workloads:**
  1. **Our real per-frame pipeline**, stage by stage: imdecode, resize (INTER_AREA), cvtColor BGR→Lab, warpPerspective, Sobel, block statistics, ALIKED+LightGlue DNN, ridge.
  2. **The fleet cycle end to end:** 20 sites × 1 frame, and a scaled run of 880 sites × 1 frame from the cache, i.e. the whole HIVIS fleet.
- **Method:**
  - thread regimes: 1 thread pinned; nproc threads
  - 50 warm-up runs, ≥ 300 iterations
  - p50/p95/p99, throughput, CPU %
  - **$ per camera-month for monitoring every gauged HIVIS camera every 30 min**, including the COOL fee
  - break-even line
  - output equivalence (max abs diff and PSNR per stage; stage estimates identical to within ±0.01 ft)
  - provenance: `cv2.__file__`, version, `getBuildInformation()` hash, AMI id, instance-identity document
- **Honesty:** report slowdowns if any, and say which stages COOL does not accelerate (DNN). Amdahl breakdown.
- **Deliverables:** `bench/run_cool_bench.py` (one command, launches and terminates), `results/cool_bench/*.csv`, `docs/COOL_BENCHMARK.md`.
- **Cost:** a short-lived instance, under $2. Log it.

## 3. Report (`report/REPORT.md` → PDF), v1 Fri, v2 Sat, final Sun noon
Sections required by the rules: problem; users; architecture; OpenCV 5 implementation; AWS deployment; evaluation; limitations; responsible use.

- **Evaluation:**
  - the frozen protocol and kill test v2 table
  - outage gap-fill
  - flood state
  - year-long CV (0.38 ft, seasonal drift)
  - registration ablation (ORB vs ALIKED+LightGlue)
  - classical waterline vs scene model (1/20 vs 9/17 on the fit window, from D-0006)
  - agent eval (W2)
  - COOL (this sprint)
- **Limitations:** daylight only; calibration needs gauge history (so it can't yet transfer to ungauged cameras); view changes; seasonal drift; 0/20 against 15-minute persistence while the gauge is online.

**Every number links to a results file.** Add `scripts/check_report_numbers.py`, which greps the numbers in REPORT/README/judge page and asserts each one appears in a committed results file.

## 4. Docs
- **`docs/ARCHITECTURE.md`:** system diagram plus agent loop diagram, Mermaid → PNG/SVG committed.
- **`docs/OPENCV5_USAGE.md`:** table of OpenCV 5 call → what it does → what breaks without it.
  - Calls: ALIKED, LightGlueMatcher, USAC_MAGSAC, warpPerspective, Sobel, cvtColor, FaceDetectorYN, imwriteanimation, dnn engine, phaseCorrelate.
- **`docs/RESPONSIBLE_USE.md`:**
  - not a replacement for official gauges or warnings
  - human approval for alerts
  - privacy: face blur, no images to the LLM
  - public-domain USGS imagery, with a manifest rather than redistribution
  - failure modes
  - cost guard
- **`docs/PRIOR_ART.md`:** from the research docs (Chapman, Vandaele, Xu & Wang, USGS NWDTW, Eltner, RISE, GRIME-AI, OTT/Tenevia). State our narrow, true claim.
- **`docs/REPRODUCE.md`:** fresh clone → tests → kill-test rescore from cached features → bench → deploy. Time each step on a clean checkout.

## 4b. Rival-driven evaluation additions (Fri). See `docs/research/2026-10-22_rivals.md`.
A direct rival, **StageSight**, appeared on Oct 20 (github.com/Waqar-msx9t/stagesight).
- **What it does:** reads the staff plate on **one** USGS NIMS camera — Hancock NY 01421500, which is also one of our sites — using an HSV mask, connectedComponents and DNN OCR, with no gauge calibration.
- **What it reports:**
  - **RMSE 0.26 ft** (bootstrap CI 0.20–0.31) on the 29 Jul 2026 flood; 0.34 ft on 4–5 Sep.
  - It returns a number for only **2.4% of hourly frames**.
  - It has a Bedrock agent with human approval and SNS, fault-injection evaluation 3× per model, and COOL on c8g.

Our edge: 20 cameras, no plate needed, much higher coverage. Match its rigor:
1. **Head-to-head at Hancock.**
   - Score our scene model on StageSight's two events (29 Jul 2026; 4–5 Sep 2026) using a **leave-event-out refit**: drop ±7 days around each event from calibration, everything else as in D-0007.
   - Report RMSE + bootstrap 95% CI, MAE, and **coverage = % of hourly frames (24 h and daylight-only) with an estimate**. Use their two baselines where they apply: plate fitted to the gauge, and a linear pixel fit.
   - Commit `results/headtohead_hancock/`.
   - Wording: name StageSight factually and respectfully, and state the different assumptions. They need a red-marked plate and no gauge history; we need gauge history and no plate.
2. **Bootstrap 95% CIs** (block bootstrap by day) for every per-site MAE/RMSE in kill test v2. Add them to the report and `/judge` from a new results CSV. Don't edit the frozen results files; write `results/kill_test_v2_ci.csv`.
3. **Coverage table on page one:** for each site, % of all hourly frames and % of daylight frames that got a stage estimate. Total "camera-hours of stage per day" across the fleet.
4. **"Not claimed" section** in the README and the report: not a replacement for gauges; no night; no ungauged transfer yet; doesn't beat 15-minute persistence while the gauge is online; synthetic faults are labelled as such.
5. **COOL:** also report **per-kernel** speedups (resize, cvtColor, Sobel, warpPerspective, imdecode) alongside end to end, plus a **fleet-scaling curve** (cameras vs wall time and $). The field has found COOL roughly flat end to end, so honesty plus the per-kernel and fleet framing is what will stand out.

## 5. Failure gallery (Sat)
`results/failures/`: 8–10 concrete cases, each with an image, the numbers and one paragraph:
- night/IR
- fog/lens
- view change (Pecatonica/White Rock)
- Tenmile flash flood miss
- Root River far bank
- seasonal vegetation drift
- tidal First Mallard

## 6. Stretch, only after Sat 12:00 CT and if everything above is on track
Onboard 10 more gauged HIVIS cameras (prefer Texas: Guadalupe at Comfort, Blanco at Wimberley, San Antonio River) with ≥ 90 days of history through worker-q. Report a "few-shot onboarding" curve: MAE vs days of calibration.

## Acceptance
- [ ] README + CLAUDE refreshed (Thu).
- [ ] COOL benchmark committed with provenance and a cost table, or a documented reason it couldn't run.
- [ ] REPORT.md final + PDF; `check_report_numbers.py` passes.
- [ ] ARCHITECTURE / OPENCV5_USAGE / RESPONSIBLE_USE / PRIOR_ART / REPRODUCE / DEPLOY done; fresh-clone times recorded.
- [ ] Failure gallery committed.
