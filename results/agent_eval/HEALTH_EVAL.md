# Fleet camera-health QA: what the history says (W2, D-0013 W2-3)

**Inputs:**
- `scripts/agent_health_eval.py` → `health_eval.json` (v2, 59 sites, 19,611 site-days)
- `health_eval_v1.json` (v1, 39 onboarded sites only)

**Spot checks:** done by eye on the contact sheets the script writes to `runs/agent_health_eval/`. They are local only, because the sheets are raw frames. Each spot check is a small sample; read the precision figures as rough.

| check | v2 result over the history | how it was checked | verdict |
|---|---|---|---|
| **offline** (> 6 h without a daylight upload) | **315 outages at 34 of 59 sites**; longest 334 h | The NIMS upload record is the ground truth, so this is a count, not an accuracy | reliable by construction |
| **view_changed** (≥ 50 % of a day's daylight frames fail registration) | 2,561 flagged days. **Recall 0.715** against the independent SLICE_01B failure-run segments (1,427 of 1,996 unlinked segment days); 1,134 flagged days fall outside segments | The segments are ≥ 3-day runs, so single-day failures (weather, glare) count here as "outside" | useful; it also fires on bad-weather days |
| **ir_stuck_on** (daylight frames that are monochrome IR) | Saturation test: 169 candidate days. **Chroma-confirmed: 16** | v1 used saturation only and was **0 of 12** right (every one was daylight snow). v2 confirms on pixels: real IR frames have chroma 0.00, against 10–38 by day and 3.5–5.7 on snow. v2 sample: **7 of 7** are real faults (camera stuck on IR, obstructed or staring at a blank surface) | reliable |
| **poor_visibility** (formerly "lens_degradation") | 223 flagged days at 38 sites | v1 compared against calibration-season levels and was **2–3 of 12** right (it flagged leaf-off and snow days). v2 compares against the camera's own 14-day baseline; its sample is multi-day fog and fresh snow cover, **not separable from a dirty lens on sharpness and haze alone** | renamed: reported as "weather or lens", low severity |
| **gauge_vs_camera** (camera > 2.5 σ from the gauge on one side for days) | not scored on history (needs camera stage on every frame) | covered by the agent evaluation's gauge-offset, drift and flatline episodes | — |

**What we claim:**
- The fleet report reliably finds **offline cameras**, **cameras stuck in IR** and **lost views**.
- Poor visibility is surfaced with the honest caveat that it may be weather.
- Every item is a ticket draft that needs a human's approval. Nothing is sent automatically.

**What we don't claim:** dirty-lens detection.
