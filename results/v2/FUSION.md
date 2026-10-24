# Fused "RiverSight stage" on simulated gauge outages (D-0013 W4-2)

**Source:** `results/v2/fusion_summary.csv` and `fusion_sites.csv`, produced by `scripts/v2_fusion.py` (worker-q #3794, commit `6299eca`). Filter: `src/riversight/calib/fusion.py`.

## Setup
- **Outages:** about 2,000 per outage length, starting every 37 h across the calibration history. Lengths 6 h, 24 h, 72 h and 7 d. 16–19 sites (the 72 h and 7 d outages need a longer record after the first CV fold).
- **Camera readings:** out-of-fold D-0007 CV predictions, so the model had never seen that month.
- **Scoring:** every hour of the outage, night included, against the USGS gauge.
- **Information used:** each method sees only what existed before the outage started, plus the outage's own camera frames.
- **Methods:**
  - `lkv` — last-known gauge value (what a user has today);
  - `camera` — camera-only Kalman;
  - `fused` — Kalman that starts at the last gauge value and is updated by the camera;
  - `fused_bias` — `fused` plus the camera–gauge offset measured over the 48 h before the outage. This was declared the primary method before any result existed.
- **"Moving" hours:** hours when the river had moved ≥ 0.25 ft from the last gauge value, i.e. the hours that matter.

## Result: median over sites of per-site MAE (ft), camera model v1 (served)
| outage | last-known | fused | fused_bias (primary) | camera only | fused_bias beats last-known |
|---|---|---|---|---|---|
| 6 h | **0.077** | 0.083 | 0.080 | 0.323 | 3/19 sites |
| 24 h | 0.203 | **0.188** | 0.224 | 0.273 | 9/19 |
| 72 h | 0.406 | **0.257** | 0.300 | 0.289 | 15/16 |
| 7 d | 0.501 | **0.273** | 0.339 | 0.290 | 15/16 |

**Moving hours only:**

| outage | last-known | fused | fused_bias |
|---|---|---|---|
| 6 h | 0.94 | 0.76 | 0.81 |
| 24 h | 0.94 | 0.69 | 0.77 |
| 72 h | 1.14 | 0.55 | 0.64 |
| 7 d | 1.19 | 0.46 | 0.60 |

**With the v2 candidate camera:** fused is 0.078 / 0.169 / 0.217 / 0.237 ft and fused_bias 0.080 / 0.190 / 0.253 / 0.284 ft. At 72 h and 7 d, fused_bias beats last-known at 16/16 sites. On moving hours at 7 d, fused is 0.38 ft.

## What it means
- **Short outages (≤ 6 h):** the last gauge value is as good as anything. The camera does not beat persistence over a few hours (the standing product claim).
- **Multi-day outages:** the fused estimate is clearly better.
  - It nearly halves the error at 7 d (0.50 → 0.27 ft with v1, −46 %).
  - When the river actually moves, it cuts the error by 52 % at 72 h (1.14 → 0.55 ft) and 61 % at 7 d (1.19 → 0.46 ft).
  - This is the gauge-outage gap-fill the product promises, measured.
- **The pre-registered primary (`fused_bias`) is not the best variant.**
  - Anchoring the camera's offset over the prior 48 h reduces median error less than plain `fused` at every outage length from 24 h, although it wins at more sites at 72 h and 7 d (15 vs 11–13 of 16).
  - Likely cause: the camera's error depends on stage, so an offset measured at pre-outage stage is wrong once the river moves.
  - We report the primary as pre-registered. Post hoc, we recommend the plain `fused` filter for the live headline number, because it is simpler and has lower median error.
- **σ is too narrow:** the fused_bias ±2σ band contains the truth in 91 % / 85 % / 81 % / 78 % of hours (6 h → 7 d; nominal 95 %). The displayed σ should be read as a lower bound, or inflated by about 1.5× (not yet validated).
