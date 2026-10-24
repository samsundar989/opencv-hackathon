# SPRINT W5 — Fleet onboarding pipeline + real-outage evidence (scale and impact)

**Owner:** Claude Code session "W5". **Commit prefix:** `[W5]`. **Status file:** `docs/status/W5.md`.
**Owns:** `scripts/onboard_*.py`, `src/riversight/onboard/`, `data/sites/fleet_v2.yaml`, `results/onboarding/`, `results/real_outages/`, `tests/w5/`.
**Read first:** D-0007, D-0010 §3, `results/history/coverage_summary.csv`, `scripts/fetch_history.py`, `scripts/history_pass.py`, `scripts/export_site_models.py`.

## Why
- **Impact (20 pts) and the post-competition product** both depend on showing the system scales by itself: "add a camera → it calibrates itself from the gauge". Twenty hand-picked sites is a demo; an automated pipeline is a product.
- **The usefulness claim** (gap-fill when gauges go down) is currently demonstrated only on simulated outages. Real outages make it real.

## Part A — one-command onboarding (`python scripts/onboard_site.py <cam_id>` and `--batch fleet_v2.yaml`)
1. **Candidate pool:** NIMS cameras with an `nwisId` gauge, active in the last 48 h, a gauge with 00065 stage, and ≥ 120 days of archive.
   - Prefer variety: big rivers, Texas flash-flood creeks (Guadalupe at Comfort, Blanco at Wimberley, San Antonio River), cold-climate sites, structures in view.
   - Rank by a quick score: archive coverage, daylight share, stage variability (p95−p5), and registration feasibility (ORB/ALIKED inliers on 10 sample frames).
2. **Pipeline:**
   1. Fetch history: every 2 h daylight, plus hourly on event days (existing scripts).
   2. Register through worker-q at **high** priority.
   3. Fit with the frozen D-0007 setting.
   4. Forward-chaining CV → tier.
   5. Export the bundle.
   6. Write `results/onboarding/<cam>.json`: coverage, CV metrics, tier, wall-clock time per stage.
3. **Target:** onboard **≥ 20 new sites by Sun 12:00 CT**, aiming for 40 live total. Only tier A/B sites go live (D-0010 §3), handed to W1 as bundles + `fleet_v2.yaml`.
4. **Few-shot curve:** for 10 sites, CV MAE vs days of calibration (14 / 30 / 60 / 90 / 180 / 365) → `results/onboarding/fewshot.csv`. This answers "how long until a new camera is useful?".
5. **Report the cost to onboard one camera:** API calls, CPU-minutes, $, wall time. Project it to all ~880 gauged HIVIS cameras.

## Part B — real gauge-outage evidence
1. Scan 12 months of USGS IV 00065 at **all gauged HIVIS sites**, batched politely within the OGC key quota, for **gaps ≥ 6 h** and for periods flagged with equipment/ice qualifiers (`Eqp`, `Ice`, `Dis`, `Mnt` in the IV qualifiers where present).
2. Intersect with periods where the camera produced daylight frames.
3. For the sites already calibrated (the 20, plus newly onboarded ones whose calibration excludes the gap ±7 days), run the camera through the gap and score it against the gauge record **once the gauge returned** (the readings on either side of the gap, plus any later-approved backfill if USGS published one). Compare with last-known-value fill.
4. Output `results/real_outages/{catalog.csv, scored.csv, README.md}`. **Even 2–3 real outages bridged by the camera is the single strongest impact evidence we can add.** If none is scoreable, say so and publish the catalogue: how often gauges at camera sites go dark.

## Gates
- **Sat 12:00 CT:** pipeline runs end to end on 3 new sites; outage catalogue v1.
- **Sat 22:00 CT:** ≥ 12 new sites through CV; real-outage scoring done.
- **Sun 12:00 CT:** final batch handed to W1; few-shot curve committed.
