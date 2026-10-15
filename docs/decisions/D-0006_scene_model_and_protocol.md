# D-0006 — 2026-10-14 (evening CT) — Answer to Q-0005/Q-0006: no pivot; scene model replaces the waterline detector; pre-registered kill-test protocol v2 (Cowork for Samuel)

Evidence is in `docs/research/2026-10-14_waterlevel_investigation.md` and `experiments/cowork_2026-10-14/`. On the worker's own fit-window protocol, detector-free scene regression reaches MAE ≤ 0.25 ft at 9/17 sites; the classical transects reached 1/20. The skill comes from water pixels (confound control).

## Rulings

1. **Q-0006 → option (a), modified.** Stay on RiverSight. The **primary estimator** becomes the *scene model*. Transects and the classical waterline detector are demoted to overlay/QA only. The water-seg net is no longer on the critical path (demo overlay only, if time allows). The scene model is:
   - registration (unchanged ALIKED+LightGlue cascade)
   - → per-block appearance features
   - → **flood-height map** (per-block inundation threshold h*, reliability-scored) used as a learned ROI
   - → kernel ridge on ROI blocks
   - → causal smoothing / Kalman
   - → stage ± σ
2. **Q-0005 → option (a), extended.** The 10 test days stay frozen (Oct 4 00Z – Oct 14 00Z). Calibration uses **all available history before Oct 3 00Z**: target 12 months, minimum 90 days. Before scoring, hyper-parameters may be tuned only by forward-chaining CV *inside the history*.
3. **Kill-test protocol v2.** It is written down now, before any test-day scoring, so it can't be read as moving the goalposts. Scoring is once, on the frozen test days, daylight frames only, at the 20 sites in `data/sites/kill_test.yaml`.
   - **P1 accuracy:** at **≥ 10/20 sites**, MAE ≤ 0.25 ft **or** normalised MAE (MAE ÷ calibration p95−p5 range) ≤ 10%.
   - **P2 value:** at **≥ 70% of sites that have event frames** (|Δstage over 24 h| ≥ 0.25 ft) in the test window, camera MAE beats a 24-hour last-known-value fill. If fewer than 5 sites have test-window events, also report P2 on the last 30 days of history via forward-chaining CV, and label it as such.
   - **P3 registration:** ≥ 90% of daylight frames (already met: 95.7%).
   - **Also reported, but not pass/fail:**
     - all-frame MAE vs 15-minute and 24-hour persistence and vs constant median
     - simulated outage gap-fill vs last-known value for 6 h / 24 h / 72 h / 7 d
     - flood-state balanced accuracy (stage > calibration p90)
     - Spearman ρ
     - per-site tier (A staff/structure, B scene, C flood-state only)
   - **Outcomes:**
     - **PASS** = P1 and P2 and P3. Record the verdict in D-0002 together with the frozen-test table.
     - **FAIL** = fewer than 6/20 on P1 **and** P2 fails. Then narrow (do not pivot): flood-state and rise detection plus the flood-height map become the product claim.
     - Anything in between is a **partial pass**: proceed with tiers.
4. **Night frames:** v1 is daylight-only, and coverage gaps are reported. A per-site night/IR model is out of scope until after PASS.
5. **Compute and spend:** unchanged (D-0004, D-0005). All image passes run on worker-q at low priority. No RunPod or AWS spend is needed for SLICE_01B.

## Q-0004 (answered for Samuel; non-cost, reversible)
Keep `docs/AWS_ACCOUNT_NOTES.md` local-only and add it to `.gitignore`; judges gain nothing from it. Put anything judge-relevant (region, services, cost guard) in `docs/AWS_SETUP.md` without IDs.
