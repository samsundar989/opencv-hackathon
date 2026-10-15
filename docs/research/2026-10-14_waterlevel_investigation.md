# Why the kill test can't read water level yet, and what fixes it (Cowork, 2026-10-14 evening CT)

**Verdict: don't pivot.** The image carries the stage signal. The kill test is failing because of three things we can fix: the detector design, the calibration length and the evaluation framing. A detector-free *scene-regression* model, trained on the same 20 fit days with the same blocked 4-fold CV as the worker, reaches **MAE ≤ 0.25 ft at 9/17 sites (the classical detector reached 1/20)**. It beats the constant-median baseline at 14/17 (classical: 4/20) and beats 24-hour persistence on event frames at 13/16. Median MAE is **0.25 ft vs 0.47 ft**. A new per-pixel **flood-height map** (the inundation-threshold map) adds two things: a physically grounded ROI that improves accuracy further, and a demo visual nobody else has. All code and numbers are in `experiments/cowork_2026-10-14/`.

## 1. What the worker built, validated

- **Registration PASS (95.7% of 9,000 daylight frames).** This holds up, and the OpenCV-5 story is real: ORB alone registers about 40%, and ALIKED+LightGlue+USAC_MAGSAC rescues 4,892 frames. My independent SIFT+MAGSAC re-registration of the 17 sites I hold agrees: ≥97% at 13 sites. The weak sites are the same ones the worker flagged: Salt Ck 48%, Big Brook 84% (fogged lens) and Sand Ck 87%.
- **Waterline→stage FAIL is real and was reported honestly.** The test days were left unscored, as the contract requires. The failure-mode analysis in Q-0005/Q-0006 is accurate.
- **Housekeeping is clean.** Registration and detection run through worker-q at low priority. There has been no AWS, RunPod or Kaggle spend, and the AWS notes are correctly kept out of git.

## 2. Root causes (ranked)

1. **The detector design is the main problem.** Hand transects with a 1-D edge/transition detector use a few hundred pixels per site. Any reflection, shadow, vegetation edge or turbid surface flips the result. The stage signal in a river camera is spread across thousands of pixels: banks and structures go under water, the surface gets more turbid, whitewater appears over weirs, wet bands form. A learned scene model uses all of these. *Evidence:* the same frames and the same CV give 0.25 ft median MAE with scene regression versus 0.47 ft with transects (table §3).
2. **The calibration window is too short.** 15–20 days with about one event means every method must extrapolate above the training range during events. My leave-one-day-out plots show predictions plateauing at the training maximum on held-out flood days, for both methods. Prior art hits the same wall: Chapman et al. report the worst errors "when the test year exceeds the training range." **The fix is history.** NIMS archives exist back to at least spring 2025 for Pecatonica, Tenmile, Stony Brook and Brandywine (spot-checked via `listFiles`). Coverage is patchy on some days, so map it per site.
3. **The evaluation framing rewards persistence during calm periods.** When the gauge is online, 15-minute or 24-hour persistence is unbeatable at base flow, but that is not when a camera gauge matters. The camera's value is during gauge outages, between telemetry gaps, at ungauged neighbours, and during events. Against 24-hour persistence on **event frames** (|Δ24 h| ≥ 0.25 ft), scene regression wins at 13/16 sites in the 20-day protocol and 17/17 in the 30-day blocked CV.
4. **Resolution (720 px) is not the bottleneck for scene regression.** Full resolution matters only for staff-plate reading at close-up sites (Hancock, Pecatonica).
5. **Hard sites will stay hard.** Root River is a far bank at about 3 px/ft with an 11.6 ft range. Salt Creek has poor registration. Clear Fork's events happen at night (the gauge rose while frames were dark). These belong in a lower tier (flood state only, or day-only), not counted against the method.

## 3. Experiments run tonight (container, CPU, 17 sites with images; White Rock and Langham were not transferred, and First Mallard is tidal and was skipped)

**Setup**
- Hourly frames within ±10 minutes of the hour, filtered to daylight.
- SIFT+USAC_MAGSAC homography to a per-site reference frame, then warped to 320×180.
- Per 4×4 block: illumination-normalised Lab mean, Sobel magnitude and L-std, giving 3,600 blocks × 5 features.
- Hourly gauge stage (USGS OGC API, 00065).
- Predictions get a causal 3-hour median.

**Models**
- **Scene ridge:** kernel ridge regression on all block features.
- **Flood-height map:** for each block, learn the stage h* at which its appearance switches (Fisher-best split over stage quantiles, with a balanced-accuracy reliability score). At inference, each reliable block votes wet or dry, and the stage is the value that agrees with the most votes.
- **Water-block ridge:** ridge restricted to blocks the flood-height map marks as reliable (acc ≥ 0.85, chosen on training folds only).

### Same protocol as the worker (first 20 days, blocked 4-fold CV) — `compare_fit20.csv`

| | Scene ridge | Water-block ridge | Flood-height map (vote) | Classical transects (worker) |
|---|---|---|---|---|
| sites with MAE ≤ 0.25 ft | **9/17** | **9/17** | 6/17 | 1/20 |
| beats constant median | **14/17** | — | 11/17 | 4/20 |
| beats 24 h persistence (all frames) | 12/17 | — | — | 4/20 |
| beats 24 h persistence (event frames) | **13/16** | — | — | — |
| median MAE (ft) | 0.25 | **0.22** | 0.33 | 0.47 |

### Per-site results (fit-20 protocol, ft)

| site | scene ridge | classical (worker) | const median | 24 h persistence | event frames: ridge / persistence |
|---|---|---|---|---|---|
| NY Hancock (staff) | **0.04** | 0.05 | 0.20 | 0.09 | — |
| NY Neversink | **0.03** | 0.29 | 0.09 | 0.11 | 0.08 / 0.48 |
| PA Brandywine | **0.11** | 0.33 | 0.27 | 0.30 | 0.17 / 0.93 |
| TX Buffalo Bayou | **0.12** | 0.41 | 0.17 | 0.21 | 0.68 / 0.90 |
| CO Sand Ck | **0.13** | 0.29 | 0.28 | 0.11 | 0.15 / 0.44 |
| CO Animas | **0.21** | 0.41 | 0.71 | 0.32 | 0.16 / 0.64 |
| WI Swan Ck | **0.22** | 0.72 | 0.42 | 0.31 | 0.63 / 1.50 |
| TX Clear Fk | **0.25** | 0.48 | 0.21 | 0.21 | 0.81 / 0.90 |
| TX Cowhouse | **0.25** (water-block 0.05) | 1.03 | 0.24 | 0.19 | 1.74 / 1.40 |
| NJ Stony Brook | 0.29 | 0.42 | 0.50 | 0.35 | 0.70 / 1.06 |
| TX Tenmile | 0.33 | 0.47 | 0.40 | 0.36 | 1.46 / 2.26 |
| NJ Big Brook | 0.37 | 0.50 | 0.34 | 0.20 | 1.03 / 0.95 |
| OH Bean Ck | 0.37 | 0.75 | 0.72 | 0.37 | 0.60 / 0.87 |
| WI Pecatonica | 0.41 | 0.38 | 1.23 | 0.61 | 0.75 / 1.68 |
| OH East Fork L. Miami | 0.42 | 1.46 | 1.48 | 0.74 | 0.49 / 1.91 |
| IL Salt Ck | 0.64 | 1.37 | 1.43 | 0.81 | 0.64 / 1.12 |
| MN Root River | 1.65 | 3.20 | 1.87 | 0.81 | 2.81 / 2.42 |

Notes on these numbers:
- These are fit-window numbers only. The 10 test days were not touched; my run used the first 20 days, exactly like the worker.
- Large-range sites (Pecatonica 6.3 ft, East Fork 6.8 ft, Tenmile 10 ft) have higher absolute MAE but rank-correlate well (Spearman ρ 0.7–0.9).

**Full 30 days, blocked 4-fold** (`results_blocked4.csv`):
- Scene ridge: MAE ≤ 0.25 at 10/17.
- Beats constant median at 16/17 and 24-hour persistence at 13/17 (17/17 on event frames).
- Flood-state balanced accuracy (stage > median + 0.5 ft): median 0.82, vs 0.77 for 24-hour persistence.

**Confound control** (`control.csv`): ridge on *non-water* blocks gives median 0.37 ft, often worse than constant. Ridge on the blocks the flood-height map selects gives 0.22 ft. The skill comes from pixels that physically respond to water, not from lighting or date drift. This is the honest check judges will ask about.

**Flood-height map visual** (`floodheight_maps.jpg`): at Pecatonica it recovers a clean colour-graded bank: red pixels wet at 4.6 ft, cyan and blue pixels wet only near 9 ft. It is a literal map of where the water reaches at each stage, learned from the gauge with no survey. Agent H found no published equivalent. At Stony Brook, Buffalo and East Fork it is noisier, because the water-surface appearance (turbidity, whitewater) changes too. That is still useful for the regressor; a longer history should sharpen the map.

## 4. What prior art says, and where we stand

- **Same family as ours:**
  - Chapman et al. (2021 preprint, 2024): OpenCV scalar features → regressor → Kalman filter; MAE 5–10 cm on year-long simulated gaps, with 7 years of training data.
  - Vandaele et al. 2023: whole-image CNN → z-scored level; r 0.80–0.94.
  - Xu & Wang 2025 (one HIVIS site): ResNet-50; RMSE 0.40 ft.
  - The USGS NWDTW 2026 talk: EfficientNet full-scene regression plus staff-plate segmentation.
- **Where that leaves us:** scene regression is the validated approach, and our 0.25 ft median with 15 days of training is in the expected range. With 6–12 months of history, 0.1–0.2 ft is realistic at good sites.
- **Our differentiators** (keep these in the pitch):
  1. The **flood-height map**: per-pixel inundation thresholds learned from the gauge. It is the explainability layer, the learned ROI, and the way to **draw forecast flood extent into the camera image**.
  2. **Fleet-scale self-calibration** across HIVIS with OpenCV-5 registration (ALIKED+LightGlue, 95.7%).
  3. **Honest skill reporting** against gap-fill baselines, plus a gauge-sanity QA agent that flags shifts like Wang 2025's 0.6 m offset.
  4. The **AWS + agent** loop (fleet triage, outage gap-fill, alerts).

## 5. Fix list, in order

1. **Replace the waterline detector with the scene model as the primary estimator:** registered block features → flood-height map ROI → kernel ridge → Kalman or causal smoothing → stage ± σ. Keep transects and the classical detector only as an overlay or QA.
2. **History:** 6–12 months per site (daylight, every 2 h, plus hourly on event days). Use forward-chaining CV inside the history.
3. **Pre-registered protocol (D-0006):** score the frozen 10 test days once. Primary metrics: event-frame MAE, outage gap-fill vs last-known value (6 h, 24 h, 72 h, 7 d), flood-state balanced accuracy, and normalised MAE. All-frame MAE vs persistence is reported but is not the bar.
4. **Feature upgrade (optional, if v1 is tight):** DINOv2-S patch tokens via `cv2.dnn` (OpenCV 5 lists DINOv2 at 21 ms on CPU). This replaces the hand-crafted block features and stays OpenCV-native.
5. **Tiers:**
   - A, staff/structure close-ups (Hancock, Pecatonica): add staff-plate reading later.
   - B, scene regression.
   - C, far, night or poor registration: flood state only.
6. **Night:** v1 is daylight-only, and the gaps are disclosed. IR or lit-night frames can become a second model per site later.
7. **Water segmentation (skywater_seg / Vandaele weights) and SAM:** no longer on the critical path. Use them for the demo overlay (SAM prompted by the flood-height map) if time allows.

## 6. Pivot criteria (if the Oct 17 frozen-test re-run fails)

- **Fail, defined:** fewer than 6/20 sites reach MAE ≤ 0.25 ft or nMAE ≤ 10%, **and** the camera loses to last-known value on event frames for 24-hour outages at most sites.
- **If it fails, narrow, don't pivot:** RiverSight becomes flood-state and rise detection plus the flood-height map. That is tier C for all sites, and persistence is blind to it by construction.
- **Not recommended:** a full project switch (for example to Porter). There isn't enough time left before Oct 26.
