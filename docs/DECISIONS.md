# DECISIONS (append-only; D-NNNN)

## D-0001 — 2026-10-13 — Project = RiverSight (Samuel: "go on riversight")
Context: `docs/research/ideas.md`, `docs/research/prior-art.md`, `docs/research/rivals-oct13.md`.
Decision: build RiverSight per `docs/PLAN_2026-10-13_RIVERSIGHT.md`. Alternatives (Porter, SkyFix) are fallbacks only if SLICE_01 fails.
Constraints restated by Samuel: use the latest globally installed Python environment; GPU jobs via workerq (read its docs first); RunPod credits are limited and shared — use only when needed; get to a POC and working demo ASAP.

## D-0002 — (pending) — Kill test verdict
To be written by Claude Code at the end of SLICE_01 with the per-site table (PASS requires registration ≥90% and MAE ≤0.25 ft at ≥10/20 sites on the 10 test days).

## D-0003 — 2026-10-14 — AWS Region us-east-2, profile `riversight`, Agent Toolkit for AWS
Context: Samuel's AWS project uses the new AWS experience with assigned Region us-east-2. Projects can only create Regional resources in their assigned Region (us-east-1 is allowed only for CloudFront, global WAF and their CloudWatch Logs).
Decision: all Regional resources (EC2/Graviton, S3, DynamoDB, Bedrock, Step Functions, Lambda) go in us-east-2. CLI auth is `aws login --profile riversight` (no long-lived access keys). The Agent Toolkit for AWS (AWS MCP server + skills) is configured against that profile; its service endpoint is us-east-1 by design. AWS rules from the toolkit are appended to CLAUDE.md between markers; project rules win on conflict.
Open risks: confirm in us-east-2 that the COOL AMI, c8g/c9g Graviton instances and the Bedrock models in the plan are available, and that cross-Region inference profiles aren't blocked by the project's SCPs.

## D-0004 — 2026-10-14 — Hard AWS budget cap: $100 (Samuel)
Full ruling: `docs/decisions/D-0004_budget_cap.md` (appended here per Cowork's request).
Summary: total AWS charges for the competition ≤ $100. Before any EC2 launch, create Budget `riversight-monthly` ($100; alerts 25/50/75/90% to Samuel) + stop-EC2 action at 90% + CloudWatch billing alarm, all in `infra/`. Minimal live stack only. Any action expected to cost > $10 → `Q-NNNN` first. Raising the cap needs Samuel's explicit OK after D-0002 PASS and the SLICE_02 fleet table.

## D-0005 — 2026-10-14 — Heavy local jobs go through worker-q at low priority
Context: the box is shared across agents/projects; worker-q docs at `C:\Users\samsu\Documents\gpu-queue\README.md` (CLI `workerq`, alias `gpuq`). Samuel (Oct 14): RSNA knee detection and arc-whest have priority for now.
Decision: every RiverSight job that is heavy in RAM, CPU or VRAM (batch registration/waterline over thousands of frames, SAM2 pseudo-labelling, seg training, large inference) is submitted as

    workerq submit --project riversight --priority low --gpus 0 --ram <GiB> --cpus <n> --node local \
      --describe "<what>" --blocks "<what waits>" [--eta <dur>] [--preemptible] -- \
      C:/Users/samsu/AppData/Local/Python/pythoncore-3.14-64/python.exe scripts/<script>.py <args>

Gotchas learned on Oct 14: (1) bare `python` inside a job resolves to an interpreter without our deps — always pass the absolute 3.14 path; (2) CPU-only jobs need `--gpus 0` (the default requests a GPU); (3) passthrough only links directories that contain no committed file, so we pass `data/raw`, `data/derived`, `models/onnx` (not `data/`, which holds committed site YAMLs); (4) `--node local` because the image cache is not staged on the 3080ti worker yet; (5) scripts put `<repo>/src` first on `sys.path` so the job runs the snapshot's code, not the editable install's live tree.

`.gpuq.toml` sets `[project] priority = "low"`, `passthrough = ["data/raw", "data/derived", "models/onnx"]` and `outputs = ["results", "runs"]`. Scripts write results to absolute paths inside the repo and report progress to `$WORKERQ_PROGRESS`. Light work (API fetches with ≤4 concurrent downloads, unit tests, single-frame debugging) runs directly. Never run `workerq priority`; never bypass the queue because the GPU looks idle.

## D-0005a — 2026-10-14 — (first filed as D-0006; renumbered the same evening because Cowork's D-0006 below claimed the number) Gauge stage source: OGC API where available, legacy NWIS IV otherwise (identical values)
Context: the OGC API key quota (1000 req/h) was exhausted twice on Oct 14 (screening + crash-recovery refetch). The legacy `waterservices.usgs.gov/nwis/iv` service returns the same USGS instantaneous-value record and accepts many sites per request.
Check: on the 3 kill-test sites that have both, every overlapping 15-min reading is identical (max |diff| = 0.0000 ft; Clear Fk Trinity 2881/2881, Swan Ck 4065/4065, Brandywine 2869/2869 matched; OGC has a few extra points only in the ±1 h padding).
Decision: `data/derived/<cam>/stage.parquet` carries a `source` column (`ogc` | `nwis_iv_legacy`); 3 sites ogc, 17 legacy IV for SLICE_01. Later slices prefer OGC (batched within quota) and keep the source column. Bug fixed alongside: `fetch_sites.py` previously never saved `stage.parquet`.

## D-0006 — 2026-10-14 (evening CT) — No pivot; scene model replaces the waterline detector; kill-test protocol v2 (Cowork for Samuel; answers Q-0005/Q-0006)
Full ruling: `docs/decisions/D-0006_scene_model_and_protocol.md`. Evidence: `docs/research/2026-10-14_waterlevel_investigation.md`, `experiments/cowork_2026-10-14/`. Executed by `docs/slices/SLICE_01B_SCENE_MODEL_RERUN.md`.
Summary:
- Primary estimator = **scene model**: registration → per-block appearance features → flood-height map (per-block inundation threshold h*, reliability-scored) as ROI → kernel ridge → causal smoothing/Kalman → stage ± σ. Transects/classical detector demoted to overlay/QA; seg net off the critical path.
- Test days stay frozen (Oct 4 00Z – Oct 14 00Z). Calibration uses history before Oct 3 00Z (target 12 months, min 90 days). Tuning only by forward-chaining CV inside the history.
- **Protocol v2** (pre-registered, daylight frames, 20 sites of `data/sites/kill_test.yaml`, scored once): **P1** ≥10/20 sites with MAE ≤ 0.25 ft or nMAE (MAE ÷ calibration p95−p5) ≤ 10%; **P2** camera beats 24 h last-known-value on event frames (|Δ24h| ≥ 0.25 ft) at ≥70% of sites with events (if <5 such sites, also report P2 on last 30 history days by forward-chaining CV, labelled); **P3** registration ≥90% (met: 95.7%). Reported, not pass/fail: all-frame MAE vs 15 min/24 h persistence and constant median; outage gap-fill vs last-known value at 6 h/24 h/72 h/7 d; flood-state balanced accuracy (stage > calibration p90); Spearman ρ; tier A/B/C.
- **PASS** = P1∧P2∧P3 → verdict in D-0002. **FAIL** = <6/20 on P1 and P2 fails → narrow to flood-state/rise detection + flood-height map (no pivot). Otherwise **partial pass** → proceed with tiers.
- Night frames out of scope for v1 (gaps reported). Compute/spend unchanged (D-0004, D-0005); no RunPod/AWS spend for SLICE_01B.
- Q-0004: `docs/AWS_ACCOUNT_NOTES.md` stays local-only (gitignored).

## D-0007 — 2026-10-15 (14:43 CT) — Frozen global scene-model setting for the kill test v2 (Claude Code, per SLICE_01B step 3)
Recorded **before** the frozen test days (Oct 4 00Z – Oct 14 00Z) were read. Config: `results/scene/frozen_config.json`; sha256 of the config and of every scoring module in `results/constants.sha256` (config `aa81e492…2622`).
- **Setting (global, all sites):** block size 4 px (3,600 blocks), flood-height ROI reliability ≥ **0.80** (fallback to all blocks below 50 ROI blocks), kernel-ridge **λ = 1.0**, causal **1-D Kalman** smoothing. Kalman parameters: q = variance of the training gauge's hourly increments; r = var(LOO residuals) · (1 − ρ₁).
- **How chosen:** forward-chaining monthly CV with a 7-day gap, inside the calibration data only (history Oct 2025 – Oct 2 2026 plus the SLICE_01 fit window before Oct 3 00Z). 36 settings were tried. The selection rule was fixed in `scripts/scene_tune.py` (commit `96daf05`) before any CV result existed: most sites meeting P1 on pooled out-of-fold predictions; ties go to the lower median nMAE.
- **CV evidence:** P1 met at **9/20** sites; median nMAE **0.145**; median MAE 0.380 ft. Sources: `results/scene/tune_cv_summary.csv`, `tune_cv_sites.csv`. Runner-ups: 8/20 at λ = 3 or 0.3. Year-long forward chaining is much harder than the 20-day fit-window CV (gate: median 0.278 ft), because seasons drift and early folds train on 1–2 months.
- **Pre-registered reporting rules (not pass/fail):**
  - event site = ≥ 3 scored frames with |Δ24h| ≥ 0.25 ft;
  - tier A = Hancock (staff) and Pecatonica (structure);
  - tier C = test-day registration < 0.80, or CV Spearman < 0.5, or < 90 calibration days;
  - every other site is tier B.
- **σ per site** = std of that site's out-of-fold residuals for this setting.
- **Calibration data per site:** see `results/history/coverage_summary.csv`. Frames from history periods registered to a reference that could not be linked back to the current view are excluded (`data/derived/<cam>/history/segments.csv`). Camera view changes were found at Pecatonica (11 failure runs), White Rock (6), Big Brook (2: different view until May 2026), Sand Ck, Salt Ck, Brandywine and First Mallard.

