# D-0010 — 2026-10-23 (Fri 16:15 CT) — Pre-registered prospective live evaluation; governance for a model v2; fleet expansion (Cowork)

Pre-registered **before** the first live reading is served. Evidence is only valid if the rules are fixed before the data exists.

## 1. Prospective live evaluation (W1 owns, W3 reports)
- **The models under test** are the live bundles **as first deployed** (`model_sha` per site, recorded in `results/live_prospective/frozen_models.json` at first deploy, with sha256). These bundles are scored for the whole period, even if a later version replaces them in serving.
- **Period:** from the first deployed cycle until **Mon Oct 26 12:00 CT** (code freeze) for the submission. The scorer keeps running through Nov 9 for the post-competition record.
- **What's scored:** every daylight cycle reading with registration OK, against the **USGS gauge reading closest in time within ±20 min**. Readings flagged `OUT_OF_RANGE` count separately as "saturated, gauge trusted", never as camera numbers.
- **Metrics, per site and fleet:**
  - MAE and median AE
  - % within ±0.25 ft
  - coverage: % of cycles with a camera number
  - flags raised, and agent decisions with their outcomes
- **Baseline:** the same comparison against a 24 h last-known gauge value.
- **Output:**
  - `scripts/score_prospective.py` → `results/live_prospective/{readings.csv, summary.json, per_site.csv}`, refreshed hourly by the worker and committed daily.
  - A `/judge` tile: "Live since {date}: N readings, median abs error X ft (frozen live models)".
- **Wording:** this is a truly out-of-sample, forward-in-time result, and it gets reported whatever it shows.

## 2. Model v2 governance (W4)
- v2 (DINOv2 features via `cv2.dnn`, plus seasonal robustness) may only be compared to v1 through the **same forward-chaining monthly CV inside the history** used for D-0007, and through the prospective live stream as a **shadow model** that scores alongside v1 without being served.
- The frozen kill-test v2 numbers are never recomputed or replaced. v2 is reported as "a candidate model, evaluated by forward-chaining CV and live shadow scoring."
- v2 replaces v1 in serving only if **all** of these hold by **Sun Oct 25 12:00 CT**:
  1. Year-long CV median MAE improves by ≥ 15% relative to v1 (0.380 ft → ≤ 0.323 ft) with no site worse by > 0.1 ft.
  2. Shadow live median AE is no worse than v1's.
  3. W1 confirms the cycle stays < 5 min on the worker.

  Otherwise v2 stays a documented experiment. Cowork makes the call, logged as a D-entry.

## 3. Fleet expansion (W5)
- New sites are onboarded with the **frozen D-0007 setting**, with no per-site tuning.
- Each site is scored by the same forward-chaining CV and by the prospective stream from its first live cycle.
- Expanded sites are listed as "onboarded Oct 24–25, not part of the frozen test" everywhere.
- A site goes live only if its CV meets tier B or better (D-0007 tier rules). Tier C sites stay listed in the onboarding results but are not served.
