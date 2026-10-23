# W3 → Cowork brief, Fri 2026-10-23 ~15:30 CT

For the strategist. Full log: `docs/status/W3.md`. All W3 work is pushed; every number below comes from a committed results file (`python scripts/check_report_numbers.py` passes).

## 1. Decisions for you

1. **Rework the pitch after losing the Hancock head-to-head.** We refit with each flood left out (`results/headtohead_hancock/metrics.csv`, report §6.6):
   - **4–5 Sep:** our RMSE is 0.46 ft, against StageSight's reported 0.34. Holding the gauge's value from the start of the event (0.41) also beats us.
   - **29–30 Jul flood:** RMSE 4.32 ft. Without that flood, calibration tops out at 11.97 ft; the river reached 18.08 ft. The model sits at its ceiling with an overconfident σ. Only flood state is right (recall 1.0).
   - **What it means:** a plate reader measures stages it has never seen; we can't. We should not compete on accuracy at Hancock. We compete on breadth (20 cameras, no plate), coverage (94.1 % of daylight hours, against their reported 2.4 % of hourly frames), flood state, and fleet QA. It's already written up this way, honestly, in the report and the README "Not claimed" section.
   - **Your call:** keep §6.6 as is (recommended: matching their rigor was the reason for doing it, and hiding a loss is worse), or move it to an appendix.
2. **A safety flag for W1/W2.** Readings near a site's calibrated maximum have to be shown as "at least X ft" with a flag, never as a confident number. Otherwise the live site and the agent will report a saturated value during exactly the floods that matter. `stage_max` is already in each bundle's `meta.json`. Please assign it to W1 (flag) and W2 (agent behaviour). Second, smaller ask: `LOW_QUALITY` also fires on muddy high-water frames (gallery case 2), so the agent shouldn't drop a frame on quality alone during a rise.
3. **Fix the video script and Devpost copy** (`docs/VIDEO_SCRIPT_DRAFT.md`):
   - **0:00:** "turns every one of them into a second instrument … live" overclaims: 20 cameras are calibrated. Suggest: "…can turn them into a second instrument. Twenty are live today." The "about 900" needs a source; the report allowlists ~880 citing the competition briefing.
   - **0:40:** "Those pixels vote" is wrong. The live and frozen estimator is ridge regression over the reliable blocks; the vote was an early variant.
   - **2:20 COOL:** don't pre-write a speedup. The dev box shows ALIKED+LightGlue dominating whenever ORB fails (1913.4 ms vs 67.3 ms on one thread), and the field found COOL roughly flat end to end. Write it to work with ≈1×: per-kernel numbers + $ per camera-month + "same outputs".
   - **2:45 failures:** add "a flood bigger than anything in the camera's history". It's our most important limitation and an honest, memorable beat.
   - **2:55:** "Gauges fail exactly when floods hit" is unsourced, and it sits awkwardly next to the point above. Suggest: "Gauges go dark, drift and get damaged. Cameras are already there. RiverSight makes them a check, a backup, and a picture of where the water is."
4. **Two corrected numbers** for any copy:
   - **8/20 cameras, not 7,** have history periods from a different view. The 8th is Root River; its periods may be outages rather than a moved camera. Wording: "8 of 20 cameras have periods that can't be registered to the current view."
   - The scene model met ≤ 0.25 ft at **9/19** sites on the fit window, not 9/17 (`results/scene/gate_fit20.csv`).
5. **Going public (D-0008 ruling 6):** gitleaks found 0 issues across 88 commits (`results/repro/secrets_scan_2026-10-23.json`). I'll rerun it right before Samuel decides.

## 2. Numbers safe for the video and Devpost (source in brackets)

- **14/20** sites accurate on frozen test days read once; bootstrap interval **12–16** [`kill_test_v2_verdict.json`, `kill_test_v2_ci_summary.json`]
- Median MAE **0.182 ft**, 95 % CI **0.148–0.22** [`kill_test_v2_ci_summary.json`]
- Gauge outage: camera beats the last-known value at **15/20** sites after 72 h and **18/20** after 7 days; at **0/20** against a 15-minute-old gauge [`kill_test_v2_summary.json`]
- Flood-state balanced accuracy **0.93** vs **0.75** for a 24 h-stale gauge, 9 sites [same]
- Registration **95.7 %** of 9,000 daylight frames; ORB alone **39.6 %**; ALIKED+LightGlue recovered **4,892** [`kill_test/registration_summary.csv`]
- Coverage: **94.1 %** of daylight hours (median camera); **219.4** camera-hours of stage per day across the fleet [`coverage_v2.csv`, `kill_test_v2_ci_summary.json`]
- Classical transect waterline **1/20** vs scene model **9/19** (fit-window CV) [`kill_test_v2_summary.json`]
- Year-long CV: median MAE **0.38 ft** (the honest long-run number) [`scene/tune_cv_summary.csv`]
- Fresh clone to all tests green, with results re-derived byte-identically, in **70.1 s** [`repro/fresh_clone_times.json`]
- Agent (W2, rules arm only so far): **92.3 %** task success, **0 %** false actions on clean controls [`agent_eval/REPORT.md`]. The LLM arms need Bedrock, i.e. `aws login`.

**Don't say:** "first camera water-level system"; "first on HIVIS"; "replaces gauges"; any COOL speedup before the AWS run; that we beat StageSight.

## 3. Critical path

- **Everything AWS waits on Samuel:** `aws login --profile riversight` (Q-0008), then the COOL G5 subscription (Q-0009). That blocks W1's G1 (18:00 CT today), W2's LLM arms and my COOL A/B.
- **COOL A/B:** one command once the bucket + AMI exist (`bench/run_cool_bench.py`); about two hours of m9g.large plus the COOL fee, under $2. Per plan: if G1 slips past Sat 12:00, cut COOL before the agent.
- **W3 next:** report v2 Sat, folding in W1's deployment, W2's eval and COOL; final PDF Sun noon; re-time the fresh clone at code freeze; rerun the secrets scan before going public.

## 4. What exists now (W3)

`README.md` · `report/REPORT.md` (v1, tables generated) · `docs/{ARCHITECTURE,OPENCV5_USAGE,PRIOR_ART,RESPONSIBLE_USE,REPRODUCE,COOL_BENCHMARK}.md` · `results/failures/` (9 cases) · `results/headtohead_hancock/` · `results/kill_test_v2_ci.csv`, `coverage_v2.csv` · `bench/` (harness, dev-box run done) · `scripts/check_report_numbers.py`, `report/verify_frozen.py`, `report/time_fresh_clone.py`.
