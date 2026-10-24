# SPRINT W4 — Model v2: DINOv2 patch features in `cv2.dnn` + seasonal robustness (candidate; D-0010 §2 governs)

**Owner:** Claude Code session "W4". **Commit prefix:** `[W4]`. **Status file:** `docs/status/W4.md`.
**Owns:** `src/riversight/vision/dino_features.py`, `src/riversight/calib/scene_v2.py`, `scripts/v2_*.py`, `results/v2/`, `models/onnx/dinov2*` (gitignored; record the sha256), `tests/w4/`.
**Read first:** D-0007, D-0010, `results/scene/tune_cv_summary.csv`, the W3 failure gallery (Tenmile "learned the sun", monthly drift), `docs/research/2026-10-22_platform.md`.

## Why
Year-long CV is 0.38 ft against 0.18 ft on the 10 test days, so seasonal drift (foliage, sun angle, turbidity) is our biggest accuracy gap. It is also the first thing a technical judge or a future user will ask about. A neural feature run in OpenCV 5's own DNN engine also deepens the "OpenCV 5 depth" score, which is worth 30 points.

## Steps
1. **DINOv2-S/14 in `cv2.dnn`.**
   - Export or obtain the ONNX model. The `onnx-community/dinov2-small` export is Apache-2.0; verify the licence and record the sha. Torch is allowed on the 5090 now (D-0008), and a `.venv` is fine for the export only.
   - Run it with `cv2.dnn.readNet` on the new engine; guard the enums with `hasattr`. Diff against onnxruntime (max abs diff < 1e-3) and commit the diff test.
   - Patch tokens at 224×(aspect) give a 16×28 grid: pool them into the same ROI layout as v1 blocks.
2. **Features v2** = [v1 block stats ‖ DINOv2 patch tokens, PCA-reduced on calibration data]. Reuse the flood-height ROI, and add DINO-space reliability.
3. **Seasonal robustness**, each tested by CV:
   - (a) day-of-year and solar elevation/azimuth as nuisance covariates, regressed out or used as interactions;
   - (b) per-season reference banks (registration plus feature normalisation);
   - (c) training-sample weighting by recency.
4. **Evaluation:** exactly the D-0007 forward-chaining monthly CV (same folds, 7-day gap) via `scripts/v2_cv.py` → `results/v2/cv_summary.csv` and `cv_sites.csv`. Report each ingredient as an ablation.
5. **Shadow scoring:** export v2 bundles and send them to W1. W1 runs them as a shadow alongside v1 in the live cycle, using the `shadow_stage_ft` field (coordinate with W1 through the status files).
6. Measure per-frame latency on the 5090 box (CPU) and give W1 the expected m9g/c8g cost.

## Gates
- **Sat 18:00 CT:** CV result for the best v2 configuration committed.
- **Sun 12:00 CT:** Cowork decides v2 vs v1 for serving under D-0010 §2.

Either way, the report gets a "Model v2 (candidate)" subsection with the ablation table. An honest null result is fine.

## Compute
worker-q at high priority; the 5090 for the export, CPU for CV. RunPod is a fallback only if worker-q is saturated; log any spend.
