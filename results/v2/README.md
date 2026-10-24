# Model v2 (candidate): report subsection draft for W3

Every number here comes from `results/v2/cv_summary.csv`, `cv_sites.csv`, `cv_by_month.csv` and `report.json`, produced by `scripts/v2_cv.py` and `scripts/v2_report.py`. These are **forward-chaining CV numbers inside the calibration history**, not frozen kill-test numbers. The kill-test v2 result (`results/kill_test_v2.md`) is unchanged and was not recomputed.

## What changed
v1 reads stage from hand-crafted per-block colour and texture statistics. v2 adds a second view of the same registered frame: **DINOv2-S/14 patch tokens computed by OpenCV 5's DNN engine** (`cv2.dnn.readNetFromONNX`, max abs diff 1.5e-4 against onnxruntime).
- The tokens pass through a fixed PCA (384 → 48 dims). The PCA was fitted on frames from 15 cameras outside the evaluation, with no labels.
- The flood-height map, fitted on the tokens, picks the patches that separate wet from dry ("DINO-space reliability").
- Kernel ridge then combines the two views with equal weight. The ridge λ, the reliability threshold and the Kalman filter are the frozen D-0007 settings.
- Three seasonal-robustness ingredients were tested alongside: sun-position bias correction, per-frame token normalisation and recency weighting of training data.

## How it was evaluated
- Exactly the D-0007 protocol: monthly forward-chaining folds, a 7-day gap, the same calibration frames (before Oct 3 2026), the same fixed knobs.
- The v1 row reproduces the frozen tuning result at every site (max |ΔMAE| 0.0).
- The rule for choosing the best v2 was committed before any v2 result existed (commit `1ad7bc5`).

## Result (20 sites, 28,004 out-of-fold frames)
| | v1 (D-0007) | v2 selected (`v1+dino_roi@0.5+sun`) |
|---|---|---|
| median MAE | 0.380 ft | **0.252 ft** (−33.7 %; paired-bootstrap 95 % CI of the ratio 0.59–0.90) |
| mean MAE | 0.389 ft | 0.304 ft |
| sites meeting P1 | 9/20 | 11/20 |
| sites improved | — | 19/20 (sign test p = 4×10⁻⁵) |
| worst site | — | Sand Ck, +0.015 ft |

v2 improves the median fold MAE in **every calendar month**: −16 % in October, −44 % in May and −42 % in August, the foliage months that drive v1's year-long drift (`cv_by_month.csv`).

## Ablation: what does the work
Change in median MAE relative to v1:
- **DINOv2 features carry the gain.**
  - DINO features alone: −32.3 %.
  - DINO added to v1 (equal weight): −33.5 %.
  - DINO patches restricted to v1's reliable blocks: −33.1 %.
  - All 448 patches: −31.4 %, but one site gets worse by 0.14 ft.
  - Global scene token only: −31.8 %.
- **The seasonal ingredients add nothing or hurt.**
  - Sun-position bias correction: +0.3 % on v1, −0.2 points on top of DINO. The selected configuration includes it only because of a 0.0006 ft tie-break; it is not a meaningful contributor.
  - Adding day of year: worse. With one year of history, a test month's day of year never appears in its training window, so the term extrapolates.
  - Per-frame token normalisation: no gain.
  - Recency weighting: worse everywhere (τ = 45 days: −19.9 % instead of −33.5 %). Older data is worth more than it costs in drift.
  - Per-season reference banks were not evaluated. With one year of history, forward-chaining CV can never test a season on a model that has seen that season before.

## Honest limits
- Still CV inside one year of history. The live shadow run (D-0010 §2, criterion 2) is the forward-in-time check.
- Serving v2 is Cowork's call on Sun Oct 25 12:00 CT.
- Cost: about 160 ms/frame on 2 CPU threads (this box). Expected 0.2–0.3 s/frame on the m9g.large worker, about 5 s per 20-site cycle.

## Failure cases (from `cv_folds.csv`)
v2 is worse than v1 in **18 of 139** site-month folds, and worse by more than 0.1 ft in two:
- **Root River, May 2026:** 0.52 → 0.70 ft. The site is still the worst overall, at 0.76 ft against 0.89 ft for v1. Its error is dominated by July (2.00 → 1.75 ft) and by ice/flat-gauge periods, a known gap (W5's outage catalogue lists a Root ice gap that also defeats the camera).
- **Bean Creek, Jul–Aug 2026:** +0.07 and +0.11 ft, in low summer flow. In its other nine months v2 is better, including March (1.94 → 1.72 ft) and May (0.51 → 0.19 ft).
- **Other high-error months:** Cowhouse Ck October (1.15 → 1.23 ft), Pecatonica May (1.40 → 1.24 ft) and Animas (0.65 ft over 2 folds) remain hard for both models. These are flashy or short-history sites, where the early folds train on 1–2 months.
