# SLICE_01B — Scene model + long history → re-run the kill test once (protocol v2, D-0006)

**Owner:** Claude Code. **Timebox:** start Oct 15 AM; score the frozen test days by **Oct 17 09:00 CT** at the latest. Commit prefix `[S01B]`.
**Read first:**
- `docs/decisions/D-0006_scene_model_and_protocol.md` (the rules)
- `docs/research/2026-10-14_waterlevel_investigation.md` (the why)
- `experiments/cowork_2026-10-14/README.md` (working reference code and numbers)

## Goal
Turn the reference experiment into production code inside `src/riversight/`. Extend calibration from 20 days to up to 12 months of history, tune only inside the history, then score the frozen test days **once** under protocol v2. Ship the evidence and demo visuals.

## Steps

1. **Port and test the reference (no new data yet).** Reproduce `experiments/cowork_2026-10-14/compare_fit20.csv` with your own registration cache, on the fit window only.
   - Create these modules:
     - `src/riversight/vision/scene_features.py`: block features. 320×180 warped frame, 4×4 blocks; Lab mean with L minus frame median, Sobel magnitude, L std.
     - `src/riversight/calib/flood_height_map.py`: `fit_thr`, vote prediction, reliability.
     - `src/riversight/calib/scene_regressor.py`: kernel ridge on ROI blocks (acc ≥ 0.85) with a fallback to all blocks if fewer than 50 ROI blocks; per-fold σ from residuals.
     - `src/riversight/eval/protocol_v2.py`: all metrics in D-0006.
   - Write unit tests on synthetic data, e.g. a band that wets at h* = 5 must be recovered within one quantile step.
   - **Gate:** the median fit-window MAE over the 17 shared sites is within ±0.05 ft of the reference (ridge 0.25, water-block 0.22). If not, find out why before going on: registration differences are fine, bugs are not.
2. **History.** For each of the 20 sites, map NIMS archive coverage with `listFiles`, one probe per week back to 2025-01. Archives are patchy (some days return 0), so record coverage per site.
   - Fetch daylight 720-px frames **every 2 h** for up to 12 months before Oct 3 00Z, **plus every hourly frame on days whose stage range ≥ 0.5 ft**. Fetch the matching stage (00065) from the OGC API.
   - Be gentle: ≤ 4 parallel requests, cache everything, use the API key. Expect about 2–3k frames per site; log totals.
   - Run registration through worker-q at low priority. Keep the same reference frame unless the scene changed (White Rock after the flood): then use **piecewise references**, splitting history at registration-failure runs and recording the change dates. A camera-moved event is itself a product feature (QA agent).
3. **Tune inside the history only.** Use forward-chaining monthly CV with a ≥ 7-day gap. The only knobs:
   - reliability threshold (0.8 / 0.85 / 0.9)
   - ridge λ (3 values)
   - smoothing (3 h median vs a 1-D Kalman with q, r from the residual ACF)
   - block size (4 vs 8)

   Pick one setting **globally** (not per site) and record it in `docs/DECISIONS.md` (D-0007) before step 4.
4. **Score the frozen test days once** (Oct 4 00Z – Oct 14 00Z) with protocol v2.
   - Write `results/kill_test_v2.md`: a per-site table covering P1, P2, all reported metrics and tier; time-series plots per site (camera ± σ vs gauge, with event frames shaded); and the flood-height map per site.
   - Record PASS / partial / FAIL in D-0002. No re-runs after scoring. Anything learned afterwards goes to SLICE_02+ as "v3, new test window".
5. **Demo assets (cheap, same pass).** Produce:
   - `results/demo/floodheight_<site>.jpg`: reference frame + h* colour map + legend in ft, using the best 5 sites.
   - An animated GIF per top site: frames over one event, with a stage needle (camera vs gauge) and the predicted wet area drawn from the flood-height map at the predicted stage (wet = blocks with h* ≤ ŝ).

   The second item is the "draw the flood into the image" capability we pitch.
6. **Update `docs/STATUS.md`.** List any new questions as Q-0007+ in `docs/HUMAN.md`, and keep working on other steps while they are open.

## Acceptance
- [ ] Reference reproduced on the fit window (step 1 gate).
- [ ] History coverage table + frames/stage cached for ≥ 15 sites with ≥ 90 days.
- [ ] D-0007 records the tuned global setting **before** test scoring.
- [ ] `results/kill_test_v2.md` + D-0002 verdict, test days scored exactly once.
- [ ] Flood-height maps + 1 event GIF in `results/demo/`.
- [ ] Tests green; no spend outside worker-q; no secrets committed.

## Out of scope / later
- Night models.
- Staff-plate reading (tier A, SLICE_03).
- SAM or seg overlay.
- DINOv2 features. Only do this if step 3 shows the block features are clearly the limit; then use DINOv2-S ONNX through `cv2.dnn` (OpenCV-5 native) and raise Q-0002 first if torch is needed for the export.
- AWS (SLICE_05; D-0004 guard first).
