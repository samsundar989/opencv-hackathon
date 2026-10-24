# Online recalibration, evaluated forward in time (D-0013 W4-3, shadow only)

**Source:** `results/v2/recal_summary.csv` and `recal_sites.csv`, produced by `scripts/v2_recal.py` (worker-q #3800).

## Setup
- **Strategies compared:**
  - **static:** fit once on a site's first 90 days (or first 150 frames), never refit;
  - **monthly:** refit at each month start on all earlier data;
  - **weekly:** refit every Monday on all earlier data, i.e. the proposed online refit.
- **Test set:** all three predict exactly the same 24,000 daylight frames at 16 sites. The other 4 sites have too short a record for a 90-day warm-up.
- **Data:** the calibration period only. The frozen D-0007 knobs are unchanged, and no frozen test day is read.
- **Why the monthly number differs from the CV:** there is no 7-day gap here, because an online refit predicts only the future. So "monthly" is not the D-0007 CV number (0.380 ft).

## Result (median over sites)
| | static | monthly | weekly |
|---|---|---|---|
| MAE, v1 | 0.361 ft | 0.305 | **0.240** |
| MAE, v2 candidate | 0.309 | 0.195 | **0.165** |
| test frames above the model's own calibrated range (mean over sites) | 7.9 % | 2.5 % | **1.7 %** |
| MAE on frames above the *static* model's range (2,026 frames, 15 sites), v1 | 2.51 | 2.00 | 1.82 |
| same, v2 | 2.40 | 1.77 | 1.54 |

- Weekly refitting beats fit-once at **16/16 sites** (v1).
- **Largest gains:**
  - Bean Ck: 1.48 → 0.42 ft;
  - Pecatonica: 1.01 → 0.23 ft (its view changed, so the early model was stale);
  - Neversink: 0.48 → 0.12 ft. There the share of frames above range fell from 26 % to 1.7 %.

## The Hancock lesson, measured
- A camera model can only read stages it was calibrated on. Refitting weekly cuts the share of readings that fall above the model's range by 4.6×. After a flood, the next flood of the same size is inside the range.
- **Refitting cannot help with the first flood above anything seen before.**
  - Hancock's above-range error barely moves (2.39 → 2.28 ft, v1). Its record crest was the first of its kind.
  - Clear Fork and Brandywine are the same (3 and 8 such frames).
  - That is why the live cycle flags `OUT_OF_RANGE` and shows a lower bound instead of a number, and why the gauge stays the reference.

## Status
- Shadow evidence only. The served model is unchanged (D-0013: no change before the deadline unless D-0010-style criteria are met by Mon 09:00).
- Proposed for after the deadline: a weekly refit job, Mondays 06:00 UTC, on all registered daylight frames + gauge. Its output scores as a shadow until it meets the same criteria.
