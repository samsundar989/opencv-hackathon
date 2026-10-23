# RiverSight: public river webcams as calibrated water-level instruments

**Technical report, OpenCV AI Competition 2026 (powered by AWS).** Draft v1, 2026-10-23. Sections marked _pending_ fill in as the sprint lands; every number here is generated from, or traceable to, a committed file in `results/` (`python scripts/check_report_numbers.py`).

## 1. Problem

The USGS runs hundreds of public HIVIS webcams that look at rivers next to official stream gauges. A gauge gives one number, stage in feet, every 15 minutes. When it goes down, nobody knows the water level at that site until a technician fixes it, and that can happen in the middle of a flood. When it reads wrong, nothing independent says so. The camera beside it is a second instrument that nobody reads, because pixels are not feet.

Existing camera water-level systems read a staff plate, need a surveyed site, or run on a single camera with hand tuning (`docs/PRIOR_ART.md`). None of them scale to a fleet of cameras that were never set up for measurement.

RiverSight reads stage from these cameras with no plate and no survey, by learning from the gauge's own history which parts of each scene go under water at which stage. It also checks itself: it notices when a camera has moved, when the lens is fogged, and when the camera and gauge disagree, and it hands those cases to an agent that a human supervises.

## 2. Users

- **Hydrographers and USGS field offices:** a provisional stage while a gauge is down, an early hint that a gauge is drifting, and a list of cameras that moved and need a new reference.
- **Flood forecasters and emergency managers:** flood state at sites where the gauge is out, and an image that shows what will be under water at the forecast crest.
- **The public and local media:** "what's under water at this stage" on a picture people recognise.

RiverSight is a supplement. It is not a replacement for gauges or official warnings (§7).

## 3. Architecture

![System architecture](../docs/img/architecture.svg)

Offline, each site is calibrated once from up to 12 months of frames and gauge readings. Live, one Graviton worker reads the newest frame of each of the 20 calibrated cameras every 30 minutes, produces a stage ± σ plus quality flags, and writes it to S3 behind CloudFront. Flagged readings go to the River Steward agent. Details: `docs/ARCHITECTURE.md`.

![Agent loop](../docs/img/agent_loop.svg)

## 4. OpenCV 5 implementation

Full table, with what breaks without each call: `docs/OPENCV5_USAGE.md`.

**Registration.** Every frame is registered to the site's reference: ORB + BFMatcher first, then, for the frames ORB cannot register, OpenCV 5.0's learned **ALIKED** features with the **LightGlueMatcher** (both new in 5.0, running on the new DNN engine), and a **USAC_MAGSAC** homography. The inlier ratio and reprojection error become the registration score that drives view-change detection.

**Scene model** (D-0006; setting frozen in D-0007).
1. `warpPerspective` puts the frame in reference geometry; `resize(INTER_AREA)` brings it to 320 × 180.
2. The frame is cut into 3,600 blocks of 4 px. Each block gets five features: Lab lightness (normalised per frame), a, b, `Sobel` gradient magnitude and lightness spread.
3. **Flood-height map.** For each block, a threshold h* on gauge stage is fitted so the block's features separate "stage below h*" from "stage above h*"; its accuracy is the block's reliability. Reliable blocks (≥ 0.80) form the region of interest. h* is also what the dashboard and the agent draw: every block with h* ≤ a given stage is under water at that stage.
4. A linear-kernel ridge regression (λ = 1) on the standardised ROI features gives a raw stage; a causal 1-D Kalman filter smooths it, and σ comes from out-of-fold residuals.

**QA and privacy.** Laplacian variance, glare and a dark-channel fog score flag bad frames; YuNet (`FaceDetectorYN`) blurs faces before any frame is published. `cv2.Animation` / `imwriteanimation` write the event GIFs.

**Arm64.** The live path uses `INTER_AREA` only and pads with `copyMakeBorder` instead of `warpPerspective(BORDER_REPLICATE)`, avoiding two KleidiCV issues in the 5.0.0.93 arm64 wheels (#29794, #29816).

## 5. AWS deployment

_Pending (W1, gate G1)._ Planned: us-east-2; one EC2 m9g.large (Graviton5) running the COOL OpenCV build; S3 for models, live readings and approvals; CloudFront for the dashboard; a Lambda Function URL for approvals; SNS e-mail; Amazon Bedrock (Claude Haiku 5.5, Converse tool use) for the agent; CloudWatch dashboard and alarms; an AWS Budget with a stop-EC2 action at 90 % of the $100 cap (D-0004). The worker publishes `/proof.json` with its OpenCV build provenance.

## 6. Evaluation

### 6.1 Protocol

Pre-registered before any test frame was read (D-0006):
- 20 cameras chosen for gauge history and view variety (`data/sites/kill_test.yaml`).
- Calibration: all frames before 2026-10-03 00Z (history up to 12 months, minimum 90 days). Tuning only by forward-chaining CV inside the calibration data: 36 settings, selection rule committed before any CV result existed (D-0007).
- The chosen setting and every scoring module were hashed (`results/constants.sha256`) before the test days were read.
- Test: daylight frames, 2026-10-04 00Z to 2026-10-14 00Z, scored **once** (worker-q job 2986, `scripts/scene_score.py`, which refuses to run a second time).
- Pass criteria: **P1** ≥ 10/20 sites with MAE ≤ 0.25 ft or nMAE ≤ 10 % of the calibration p5–p95 stage range; **P2** the camera beats a 24-hour-stale gauge on event frames at ≥ 70 % of sites with events; **P3** registration ≥ 90 %.

### 6.2 Headline results (verdict: PASS)

<!-- BEGIN:headline -->
| metric | value | source |
|---|---|---|
| P1 accuracy (MAE ≤ 0.25 ft or nMAE ≤ 10 %) | **14/20** sites (bootstrap 95 % interval 12–16) | `kill_test_v2_verdict.json`, `kill_test_v2_ci_summary.json` |
| median MAE across sites | **0.182 ft** (95 % CI 0.148–0.22) | `kill_test_v2_ci_summary.json` |
| median nMAE / Spearman ρ | 0.092 / 0.66 | `kill_test_v2_summary.json` |
| P2 value on event frames vs 24 h-stale gauge | **15/16** event sites | `kill_test_v2_verdict.json` |
| P3 registration, 30-day daylight frames | **95.7 %** (8611 of 9000) | `kill_test/registration_summary.csv` |
| flood-state balanced accuracy, median over 9 sites with flood frames | **0.93** vs 0.75 (24 h-stale gauge) | `kill_test_v2_summary.json` |
| coverage: daylight hours with a reading, median site | 94.1 % (47.5 % of all hours) | `coverage_v2.csv` |
| fleet camera-hours of stage per day | 219.4 | `kill_test_v2_ci_summary.json` |
<!-- END:headline -->

CIs are a block bootstrap over test days (`report/bootstrap_coverage.py`). "Covered" means at least one frame in that hour produced a reading.

### 6.3 Per site

<!-- BEGIN:per_site -->
| site | tier | frames | MAE ft [95% CI] | RMSE ft | nMAE | P1 | event MAE: camera / 24 h LKV | daylight hours covered |
|---|---|---|---|---|---|---|---|---|
| Cowhouse Ck at Old Georgetown Rd nr Ft Hood (TX) | C | 236 | 0.212 [0.141–0.320] | 0.288 | 0.15 | ✔ | 0.64 / 1.01 | 100.0 % |
| Tenmile Ck at Parkinson Rd nr Ferris (TX) | C | 119 | 0.617 [0.539–0.679] | 0.685 | 0.33 | ✘ | 0.20 / 0.84 | 90.8 % |
| Buffalo Bayou at State HWY 6 near Addicks (TX) | B | 113 | 0.268 [0.182–0.364] | 0.353 | 0.09 | ✔ | 0.23 / 1.06 | 85.8 % |
| Clear Fk Trinity Rv at Ft Worth (TX) | B | 120 | 0.133 [0.098–0.179] | 0.171 | 0.11 | ✔ | 0.20 / 0.91 | 91.7 % |
| White Rk Ck at Greenville Ave Dallas (TX) | C | 58 | 0.782 [0.695–0.880] | 0.833 | 0.72 | ✘ | 0.56 / 0.52 | 40.8 % |
| Langham Creek at Addicks Reservoir Outflow near Addicks (TX) | B | 211 | 0.487 [0.384–0.569] | 0.661 | 0.10 | ✘ | 0.57 / 2.02 | 95.0 % |
| East Branch Pecatonica River near Blanchardville Bullet (WI) | A | 113 | 0.091 [0.071–0.115] | 0.108 | 0.02 | ✔ | 0.07 / 0.34 | 94.2 % |
| Swan Creek at Lalor Road near Fitchburg (WI) | C | 113 | 0.060 [0.046–0.076] | 0.073 | 0.04 | ✔ | — | 94.1 % |
| Root River near Pilot Mound (MN) | C | 94 | 0.451 [0.362–0.541] | 0.482 | 0.10 | ✘ | — | 78.3 % |
| East Branch Delaware River at Hancock Staff (NY) | A | 114 | 0.065 [0.049–0.081] | 0.087 | 0.04 | ✔ | 0.07 / 0.59 | 95.0 % |
| Neversink River at Godeffroy (NY) | B | 114 | 0.060 [0.036–0.095] | 0.086 | 0.04 | ✔ | 0.11 / 0.51 | 95.0 % |
| Stony Brook at Princeton (NJ) | B | 111 | 0.106 [0.074–0.145] | 0.138 | 0.06 | ✔ | 0.13 / 1.09 | 92.5 % |
| Big Brook near Marlboro (NJ) | C | 58 | 0.146 [0.103–0.200] | 0.173 | 0.17 | ✔ | 0.11 / 0.40 | 48.3 % |
| East Fork Little Miami River at Perintown (OH) | B | 120 | 0.475 [0.359–0.588] | 0.545 | 0.11 | ✘ | — | 94.8 % |
| Bean Creek at Powers (OH) | B | 113 | 0.270 [0.204–0.339] | 0.312 | 0.05 | ✔ | 0.22 / 0.58 | 89.6 % |
| Animas River at Durango (CO) | B | 230 | 0.152 [0.113–0.185] | 0.167 | 0.07 | ✔ | 0.02 / 0.29 | 100.0 % |
| Sand Creek at Mouth nr Commerce City (CO) | C | 237 | 0.069 [0.060–0.078] | 0.080 | 0.09 | ✔ | — | 100.0 % |
| Salt Creek at Wood Dale (IL) | B | 119 | 0.091 [0.065–0.118] | 0.121 | 0.02 | ✔ | 0.14 / 0.90 | 99.1 % |
| Brandywine Creek at Chadds Ford (PA) | C | 233 | 0.308 [0.210–0.405] | 0.387 | 0.19 | ✘ | 0.37 / 1.92 | 99.2 % |
| First Mallard Branch nr Fairfield (CA) | B | 208 | 0.391 [0.308–0.478] | 0.523 | 0.09 | ✔ | 0.35 / 0.58 | 90.8 % |
<!-- END:per_site -->

Per-site time series and flood-height maps: `results/kill_test_v2/`. Tiers follow pre-registered rules (D-0007): A = sites with a staff plate or structure in view, C = poor test-day registration, weak CV correlation or under 90 calibration days.

### 6.4 Against baselines: where the camera adds value

<!-- BEGIN:baselines -->
| comparison (all scored frames unless noted) | camera better at |
|---|---|
| constant (calibration median) | 16/20 |
| gauge 24 h stale (persistence) | 10/20 |
| gauge 15 min stale (persistence) | 0/20 |
| event frames (\|Δ24h\| ≥ 0.25 ft): gauge 24 h stale, P2 | 15/16 event sites |
| gauge outage of 6 h: last-known value | 3/20 |
| gauge outage of 24 h: last-known value | 10/20 |
| gauge outage of 72 h: last-known value | 15/20 |
| gauge outage of 7 days: last-known value | 18/20 |
<!-- END:baselines -->

The camera never beats a 15-minute-old gauge reading. Its value appears when the gauge is down or stale: after a 72-hour outage it beats the last known value at most sites, and after 7 days at nearly all. That is the product claim: **gap-fill during gauge outages, flood state, and camera QA**, not live replacement.

### 6.5 Ablations and harder settings

<!-- BEGIN:ablations -->
| ablation | result | source |
|---|---|---|
| registration: ORB + MAGSAC alone vs full cascade | 39.6 % vs 95.7 % of 9000 daylight frames; ALIKED + LightGlue recovered 4892 frames | `kill_test/registration_summary.csv` |
| estimator: classical transect waterline vs scene model, 20-day fit-window CV, sites ≤ 0.25 ft | 1/20 vs 9/19 (scene median 0.278 ft) | `kill_test/fit_window_cv.csv`, `scene/gate_fit20.csv` |
| calibration horizon: year-long forward-chaining CV (frozen setting) | P1 at 9/20, median MAE 0.38 ft, median nMAE 0.145; 36 settings tried | `scene/tune_cv_summary.csv` |
<!-- END:ablations -->

The year-long CV is the honest long-run number. Its error is about twice the test-day error, because the scene changes with the seasons (vegetation, sun angle, sediment) and the early folds train on only one or two months. Periodic recalibration is planned for the live models (they are refit on all data up to export, and never mixed into the frozen numbers).

### 6.6 Head-to-head at Hancock, NY

StageSight, another entry, reads the staff plate on the same USGS camera (Hancock NY, 01421500) and reports two floods. The two systems make different assumptions: StageSight needs a red-marked plate in view and no gauge history; RiverSight needs gauge history and no plate. To compare fairly we refit our scene model with the frozen setting on all calibration frames **except ±7 days around each event** (leave-event-out), and score the event's registered daylight frames against the gauge (`report/headtohead_hancock.py`, `results/headtohead_hancock/`). Our windows are the UTC days of each event; StageSight's exact frame sets may differ.

<!-- BEGIN:hancock -->
| | 29–30 Jul 2026 flood | 4–5 Sep 2026 |
|---|---|---|
| gauge range in window, ft | 9.56–18.08 | 10.87–11.97 |
| our calibration max after leaving the event out, ft | 11.97 | 18.08 |
| **RiverSight RMSE, ft [95 % CI]** | 4.32 [3.44–5.07] | 0.46 [0.36–0.54] |
| RiverSight MAE / within 0.5 ft | 3.29 / 21.4 % | 0.39 / 61.5 % |
| RiverSight flood-state recall (camera above calibration p90 when the gauge is) | 1.00 | 0.92 |
| baseline: gauge value at window start held (outage at event start), RMSE | 5.53 | 0.41 |
| baseline: calibration median, RMSE | 5.40 | 1.76 |
| RiverSight coverage: hours of the window / listed daylight frames with a reading | 58.3 % / 93.3 % | 54.2 % / 100.0 % |
| StageSight RMSE as reported, ft (not reproduced by us) | 0.26 [0.20–0.31] | 0.34 |
| StageSight coverage as reported | 2.4 % of hourly frames (whole archive) | |
<!-- END:hancock -->

**Reading this honestly.**
- On the moderate September event we are worse than StageSight's reported figure, and slightly worse than simply holding the gauge's value from the start of the event.
- On the July flood we fail: with that flood left out, the calibration never saw a stage above 11.97 ft, and the scene model cannot extrapolate. It saturates near its calibrated ceiling while the river rises above it. Its Kalman σ stays small, so it is confidently wrong.
- What survives is flood state: the camera put itself above the calibration p90 on every July frame where the gauge was there.
- A plate reader measures stages it has never seen; a model calibrated from history does not. This is the main limitation of the approach (§7). The live system now has to flag readings at the edge of the calibrated range instead of reporting them as numbers.
- Our advantage is elsewhere: 20 cameras without plates, and coverage of most daylight hours, against 2.4 % of hourly frames reported for the plate reader.

### 6.7 Agent evaluation

_Pending (W2)._ Fault-injection episodes, real and synthetic (labelled), each with expected actions written before the run; Bedrock agent vs deterministic rules vs no-OpenCV-evidence ablation; task success, false actions on clean controls, latency, tokens and cost.

### 6.8 COOL on Graviton

_Pending._ COOL vs stock pip OpenCV 5.0.0.93 on the same m9g.large: per-kernel speedups, the whole per-frame pipeline, the fleet cycle, output equivalence, and $ per camera-month. Harness: `bench/`; method: `docs/COOL_BENCHMARK.md`.

### 6.9 Failure cases

_Pending (Sat)._ `results/failures/`: night/IR, fog and wet lens, view changes, the Tenmile flash flood, Root River's far bank, seasonal drift, the tidal First Mallard site.

## 7. Limitations (not claimed)

- **Not a replacement for gauges or official warnings.** The camera beats 15-minute persistence at no site.
- **Daylight only.** Night and IR frames are not scored, so the camera covers about half of all hours.
- **Needs gauge history.** Calibration uses the co-located gauge, so it does not transfer to ungauged cameras yet.
- **No extrapolation above the calibrated range.** A flood higher than anything in the calibration data is read as roughly the calibrated maximum, with an overconfident σ (§6.6). Flood state still fires.
- **Seasonal drift.** See §6.5.
- **Cameras move.** Several cameras have history periods taken from a different view (`results/kill_test_v2_summary.json`). The live system detects view changes and the agent re-anchors or quarantines.
- **Quiet test windows.** Several P1 passes come from flat test windows where simple baselines are better still (Swan Creek, Sand Creek, Big Brook; Cowhouse vs 24 h persistence).
- **Failures:** Tenmile (ρ < 0), White Rock (scene changed after a flood), Langham, Root River, East Fork Little Miami and Brandywine miss P1.
- **Synthetic faults** in the agent evaluation are labelled as such.

## 8. Responsible use

_Draft; full version in `docs/RESPONSIBLE_USE.md`._
- Readings are labelled provisional; alerts and tickets are drafted by the agent and sent only after a human approves.
- No images go to the LLM, only numbers and short summaries. Faces are blurred (YuNet) before any frame is published.
- USGS imagery is public domain. We do not redistribute raw frames; derived overlays carry a credit line.
- Spending is capped by an AWS Budget with an automatic stop.

## Reproduce

`docs/REPRODUCE.md` (_pending_): fresh clone → tests → summary and CIs from committed predictions → COOL bench → deploy.
