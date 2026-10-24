# HUMAN — questions for Samuel (Q-NNNN) and answers (## ANSWER NNNN)

Claude Code appends questions here when blocked on something only Samuel can decide or do, then continues with other work. Samuel answers inline; Cowork may also answer on his behalf for non-cost, non-irreversible items.

## Q-0001 — workerq docs location and submit command
Cowork could not read `C:\Users\samsu\Documents\gpu-queue` (folder not connected). Claude Code: read the docs there yourself and record the current submit command in `docs/DECISIONS.md` (D-0003). If that folder is not workerq, Samuel: where do the workerq docs live?

## Q-0002 — Global Python version and CUDA PyTorch
Samuel said to use the latest global environment. Claude Code: run `python --version`, `python -c "import torch;print(torch.__version__, torch.cuda.is_available(), torch.version.cuda)"` and record both in `docs/STATUS.md`. If torch is missing or has no CUDA for the RTX 5090 (sm_120 needs CUDA ≥12.8 builds), ask Samuel before installing a new torch globally.

## Q-0003 — USGS API key
Needed for comfortable rate limits: https://api.waterdata.usgs.gov/signup/ (free, instant). Samuel: paste it into `.env` as `USGS_API_KEY=...` (never into chat). Claude Code proceeds at a low request rate until then.

### Claude Code notes (2026-10-14)
- Q-0001: answered by D-0005 (worker-q docs found at `C:\Users\samsu\Documents\gpu-queue`).
- Q-0002: global Python is **3.14.4**; **torch is not installed** there. SLICE_01 doesn't need it. Before SLICE_03, Samuel: OK to `python -m pip install torch --index-url https://download.pytorch.org/whl/cu128` (or newer) into the global 3.14? If no cp314 CUDA wheel exists I will create `.venv` (uv, Python 3.12/3.13) for training only and say so in STATUS.
- Q-0003: answered — key is in `.env`.

## Q-0004 — Commit `docs/AWS_ACCOUNT_NOTES.md`?
It contains AWS account IDs, the console URL slug and the card's last 4 digits. The repo will be shared with judges, so I left it untracked. Options: (a) keep it local-only (add to `.gitignore`), (b) commit a redacted copy. My recommendation: (b). Until answered, it stays untracked.

## Q-0005 — Kill-test protocol: 20 fit days may be too short for flashy sites (early warning; verdict still pending)
Evidence so far (fit window only; test days untouched), from `scripts/kill_test.py --dev`:
- Registration is not the problem: ORB→ALIKED+LightGlue registers 98.9–100% of true daytime frames at 4 sites (sun-elevation night flag + homography plausibility QA).
- Auto transects (stage-correlation map) land on the water surface (turbidity), not shorelines → fit-window CV MAE worse than a constant-median baseline (Tenmile 0.52 vs 0.39 ft; Cowhouse 0.37 vs 0.32; Brandywine 0.30 vs 0.24).
- Hand transects (contract fallback) give **stable, stage-responsive detections**: base-flow jitter 0–3 px, clear moves at high water (Tenmile far bank 99→75 px; Brandywine pier 39→5 px for ~1.8 ft). The image carries the signal.
- But each site's 20-day fit window holds ~one event; blocked CV must extrapolate from flat folds to the event fold (CV MAE 0.37–0.79 ft), and base-flow changes (~0.05 ft) are sub-pixel at 4–20 px/ft. If the 10 test days are calm, persistence-24h is ~0.02 ft and **cannot be beaten by any camera method** at flashy creeks.
Options (Samuel/Cowork decide; I keep running the contract as written meanwhile):
- (a) Keep the 10 test days fixed, lengthen calibration history to ~80–90 days before them (USGS archives go back years; this is the plan's SLICE_02 window anyway), and score "beats persistence" only on test frames where |Δstage over 24 h| ≥ 0.25 ft (when a camera matters). Same MAE ≤ 0.25 ft threshold.
- (b) Reframe as event detection (rise onset/crest timing, ice/obstruction) where persistence is blind by construction.
- (c) Proceed on the subset of sites that pass the contract as written.
Recommendation: (a), decided **before** the test days are scored, recorded as a D-ruling so it can't be read as moving the goalposts after seeing results. Cost: ~2× more frames to register (worker-q, low priority) — about half a day of queue time at current load.

### Q-0005 update (fit window only; test days still unscored)
| site | hand transects | fit-window blocked-CV MAE (ft) | constant-median baseline (ft) | registration (daytime, QA'd) |
|---|---|---|---|---|
| WI Pecatonica (staff + wall) | 5 | **0.38** | 0.61 | 85.5% (fogged lens frames rejected) |
| TX Buffalo Bayou (channel walls) | 5 | 0.41 | — | 98.9% |
| TX Clear Fk Trinity | 5 | 0.48 | — | 99.2% |
| TX Tenmile Ck | 6 | 0.46 | 0.39 | 100% |
| PA Brandywine (pier) | 4 | 0.37 | 0.24 | 99.7% |
| TX Cowhouse Ck (piers) | 5 | 0.79 | 0.32 | 99.7% |
| TX White Rock Ck | 5 | 1.46 (coverage 74%) | — | 79.5% (bed changed after the Oct 1 flood → needs re-anchoring) |
Reading: where there is a clean structure and real stage variation (Pecatonica: p05–p95 4.5–7.8 ft) the camera beats the baseline by ~38%; where the fit window is flat with one event, it cannot be calibrated in 20 days. Supports option (a).

## Q-0006 — SLICE_01 is heading for FAIL on the classical detector; direction needed before any test-day scoring
Full fit-window evidence, 20 sites, hand transects, blocked 4-fold CV inside the 20 fit days (test days never read): `results/kill_test/fit_window_cv.csv`, `results/kill_test/registration_summary.csv`.
- **Registration passes:** 95.7% of 9,000 true-daylight frames (bar ≥ 90%); ORB alone ≈ 40%, ALIKED+LightGlue rescued 4,892 frames. This is a strong, honest OpenCV-5 result.
- **Waterline → stage does not (yet):** camera CV MAE ≤ 0.25 ft at **1/20** (Hancock staff, 0.048 ft); beats a constant-median baseline at 4/20 (Pecatonica 0.38 vs 0.61, Hancock 0.05 vs 0.14, Animas 0.41 vs 0.57, Stony Brook ≈ tie); beats persistence-24h at 4/20. No valid fit at the tidal site.
- **Failure modes (per site, in the CSV):** flat fit window with one event (flashy TX creeks; calibration can't be learned in 20 days); classical edge detector picks reflections/shadows/vegetation edges (Cowhouse, Salt Ck, Bean Ck, Root River); low px/ft far banks (Root River ~3 px/ft, Neversink); registration loss after a flood changed the bed (White Rock) or a wet/fogged lens (Big Brook, Pecatonica).
- CV here is harsher than the contract protocol (15-day fits extrapolating to the held-out event), but the gap to ≥10/20 is too large to close by protocol alone.
Per the slice contract I am **not** scoring the 10 test days and not tuning further into them. Options:
- (a) **Proceed, with the detector upgrade pulled forward:** keep the 10 test days frozen; build SLICE_03's water-segmentation waterline (SAM2 pseudo-labels on the 5090 via worker-q → small seg net → ONNX → `cv2.dnn` new engine) and lengthen calibration to ~90 days (SLICE_02 window); re-run the kill test once, same frozen test days, by ~Oct 17. Registration result already banks the OpenCV-5 story.
- (b) **Reframe** to event detection (rise onset / crest timing, camera-moved / occlusion QA), where registration + change detection already work and persistence is blind.
- (c) Switch to Porter (docs/research/ideas.md).
Recommendation: **(a)**, with (b) as the fallback narrative if the re-run also fails on Oct 17. Cost: ~1–2 GPU-hours on the 5090 (worker-q, low priority), no AWS spend.

## ANSWER 0004 / 0005 / 0006 — Cowork for Samuel, 2026-10-14 evening CT
See `docs/decisions/D-0006_scene_model_and_protocol.md` (rulings) and `docs/research/2026-10-14_waterlevel_investigation.md` (evidence).
- **0006:** no pivot. Option (a), modified: a detector-free **scene model** (registered block features → flood-height-map ROI → kernel ridge → smoothing) replaces transects as the primary estimator. On your own fit-window protocol it reaches MAE ≤ 0.25 ft at 9/17 sites (transects: 1/20). Execute `docs/slices/SLICE_01B_SCENE_MODEL_RERUN.md`.
- **0005:** option (a), extended. The 10 test days stay frozen; calibration uses up to 12 months of history (minimum 90 days); tuning happens only inside the history; scoring under protocol v2 (D-0006) happens once.
- **0004:** keep `docs/AWS_ACCOUNT_NOTES.md` local-only and add it to `.gitignore`.
- **0002 (torch):** not needed for SLICE_01B. Ask again only if DINOv2 export is needed.

## Q-0007 — 2026-10-15 — Kill test v2 PASSED; publishing frame-derived demo images; next slice (Claude Code)
SLICE_01B is done: protocol v2 **PASS** (P1 14/20, P2 15/16, P3 95.7 %). The test days were scored once. Details and caveats are in D-0002 and `results/kill_test_v2.md`. Two things need a call:
1. **Demo images.** `results/demo/` holds 5 flood-height JPGs and 2 event GIFs. Each is a USGS frame (public domain, faces blurred, none found) with our overlay, and they are committed to the judge-visible repo. Non-negotiable 7 says "don't redistribute raw images". I read these as derived demo assets (Cowork asked for them in SLICE_01B), not raw frames. **Keep them committed, or move them to a gitignored folder and show them only in the video/dashboard?** Until you answer, they stay committed.
2. **Next slice.** The setup is SLICE_02 per the plan, but some findings should shape it:
   - Year-long CV is much harder than the 20-day window: median MAE 0.38 ft out-of-fold vs 0.18 ft on the test days. Seasonal drift is the main error source.
   - 7/20 cameras changed view inside 12 months. That makes camera-moved QA, and re-anchoring after it, a core feature rather than a nice-to-have.
   - The camera's value is outage gap-fill (≥ 72 h: 15–18/20 sites) and flood state (balanced accuracy 0.93 vs 0.75), not live replacement (0/20 vs 15-min persistence).
   Recommendation: SLICE_02 fleet scale-up with the D-0007 setting frozen, plus a periodic recalibration window and the view-change detector. **Cowork to confirm.**

## Q-0008 — 2026-10-23 — AWS session expired: please run `aws login --profile riversight` (W1)
`aws sts get-caller-identity --profile riversight` says the session has expired. W1 cannot create the budget guard (D-0004), so nothing else in AWS can happen until it exists.
**Action:** run `aws login --profile riversight` in a terminal on sam-mega-pc (browser sign-in), then reply `## ANSWER 0008` or say so in the W1 chat.
Meanwhile W1 works offline on the site bundles and the local live cycle (SPRINT_W1 steps 1–2).
Heads-up for the next ask: launching the live worker from the COOL G5 AMI needs your AWS Marketplace subscription to `prodview-igdweaoo6prb6` ("COOL Graviton 5-1.0"). W1 will file that as its own `Q-` once the budget guard is live.

## Q-0009 — 2026-10-23 — Subscribe to the COOL Graviton5 AMI in AWS Marketplace (W1)
D-0008 ruling 2 runs the live worker on the **COOL G5 AMI** (m9g). Launching it fails with `OptInRequired` until the project owner accepts the Marketplace terms. That is your click, not an agent's.
**Action:** while signed in to the riversight project, open https://aws.amazon.com/marketplace/pp/prodview-igdweaoo6prb6 ("COOL Graviton 5-1.0") → *View purchase options* → *Subscribe / Accept terms*. The research note puts the software fee at about $0.005/h on m9g.large, on top of EC2. Then reply `## ANSWER 0009`.
**Meanwhile:** after the budget guard is live (needs Q-0008), W1 deploys the live site on the fallback: stock Ubuntu 24.04 arm64 with pip `opencv-python-headless==5.0.0.93`. Once you've subscribed, it redeploys on COOL with `python scripts/deploy.py --worker-ami cool --cool-ami-id <ami> --instance-type m9g.medium|large`.
**Cost:** projected spend stays under $60 through Nov 10 on either image. No single action exceeds $10.

## Q-0010 — 2026-10-23 — Accept the Bedrock model agreements for Claude Haiku 5.5 and Sonnet 5.5 (W2)
`aws login` works, thank you. Bedrock in us-east-2 denies every Claude **5.x** model for this account ("anthropic.claude-haiku-5-5 is not available for this account"). `get-foundation-model-availability` reports `agreementAvailability: NOT_AVAILABLE` with authorization, entitlement and Region all fine: the per-model **Marketplace agreement** has not been accepted. Older models (Claude Haiku 4.5, Sonnet 4.6/4.5) and Amazon Nova already work.
**Action (one click per model, legal terms + pay-per-use billing, no upfront cost):** AWS Bedrock console, us-east-2 → Model catalog → *Claude Haiku 5.5* → request / enable access (accept Anthropic's offer); same for *Claude Sonnet 5.5*. Then reply `## ANSWER 0010` or tell W2.
**Cost:** D1 plan (Haiku 3×, Haiku-no-OpenCV 3×, Sonnet 1×) is estimated at ~$6–10 total at list prices; W2 measures it in a 5-episode pilot first and logs real $ in `docs/status/W2.md`.
**If not done by Sat 10:00 CT:** W2 runs the same arms on Claude **Haiku 4.5** + **Sonnet 4.6**, which work today. Haiku 4.5 costs ~10× Haiku 5.5 per token (~$15–25 for the two Haiku arms, estimate), so W2 would run Sonnet 4.6 1× only and stay under the $100 cap; the report names the models actually used.
Meanwhile W2 validates the agent loop on Haiku 4.5 with a 5-episode dev pilot (a few cents).

## ANSWER 0008 / 0009 — Samuel via Cowork, 2026-10-23 15:59 CT
- 0008: `aws login --profile riversight` done.
- 0009: subscribed to COOL Graviton5 (`prodview-igdweaoo6prb6`) in AWS Marketplace.
- 0010 (Bedrock Claude 5.5 model agreements): Cowork is asking Samuel now; W2 keeps the Haiku 4.5 dev pilot going in the meantime.

## ANSWER 0010 — Samuel via Cowork, 2026-10-23 21:25 CT
In the Bedrock playground (us-east-2), Claude Sonnet 5.5 returns `AccessDeniedException: anthropic.claude-sonnet-5-5 is not available for this account ... contact AWS Sales`. This is an account-level eligibility gate, not an unaccepted agreement, and it can't be cleared before the deadline.
**Ruling (Cowork):**
- Use the fallback: **Claude Haiku 4.5** for the agent and the main LLM arms, and **Claude Sonnet 4.6** for the second-opinion arm. Both work today through the `us.` cross-region profiles.
- If Samuel reports that Haiku 5.5 works in the playground, use Haiku 5.5 for the Haiku arms instead.
- Arms: Haiku 3×, Haiku-without-OpenCV 3×, Sonnet 4.6 1×.
- Measure the cost in the 5-episode pilot first. Stop and file a Q- if the projected total Bedrock spend exceeds **$25**.
- The report and the dashboard name the models actually used. No 5.5 claims.
- Update 21:26 CT: Samuel confirms Haiku 5.5 is also blocked, and that **Claude Opus 4.5 works**. Same fallback: Haiku 4.5 for the main arms, Sonnet 4.6 for the second-opinion arm. W2 may add one Opus 4.5 pass on the full set, but only if the pilot shows the total Bedrock spend stays ≤ $25.

## Q-0011 — 2026-10-24 — Who should decide on the live site: the rules policy or Claude Haiku 4.5? (W2)
The final agent evaluation (frozen v3, `results/agent_eval/LLM_ANALYSIS.md`) shows the deterministic, OpenCV-evidence rules policy at **93.9 %** task success with 0 false actions on clean controls, ahead of **Claude Sonnet 4.6 (71.4 %)** and **Claude Haiku 4.5 (58.8 %)**. Today the live worker lets Haiku 4.5 decide, with rules only as the fallback.
Sonnet 4.6 is better than the rules at **fleet triage** (12/12 cycles), **gauge-drift** cases (67 % vs 0 %) and **rise alerts** (100 %).
**Recommendation:** rules take the actions; Sonnet 4.6 ranks the fleet (`triage.json`), gives a second opinion on anything that would page a human (already built: `RIVERSIGHT_AGENT_ESCALATE=1`), and reviews gauge drift. W2 can ship this as a config switch (`RIVERSIGHT_AGENT_MODE=rules_first`) in about an hour.
**Options:** (a) recommended hybrid; (b) keep Haiku 4.5 deciding; (c) Sonnet 4.6 deciding (~$0.05 per flagged reading, ~4× Haiku).

## Q-0012 — 2026-10-24 — Fleet expansion: serve every tier-B onboarded site, or a subset? (W5, for Cowork)
**Context.** The 39-site onboarding batch is about 87 % done (`results/onboarding/summary.csv`). With the frozen D-0007 setting and the D-0007 tier rules, **25 new sites are tier B** so far, and D-0010 §3 says tier B goes live. They are mostly large rivers, chosen because the stage-swing score favours them:
- **Relative error matches the frozen fleet:** median CV nMAE ≈ 0.14, against the D-0007 20-site CV's 0.145.
- **Absolute error is large:** median CV MAE ≈ 1 ft (Missouri at Hermann 1.96 ft, Wabash 2.05 ft).
- **The 24 h last-known gauge value beats the camera at most of them** while the gauge is up, e.g. Missouri below Mandan 0.58 vs 0.16 ft and Buffalo 0.64 vs 0.08 ft.
- **Clear wins:** Savannah tidal dock 0.43 vs 1.08 ft; Ottawa River near Kalida 0.86 vs 0.94 ft.

This is consistent with our claim (gap-fill and flood state, not gauge replacement). But a judge looking at a 1–2 ft error band on a site page may read it as weak.

**Options.**
1. **Follow D-0010 §3 as written:** serve all tier-B sites, labelled "onboarded Oct 24–25, not part of the frozen test", with σ shown. Also adds load to W1's cycle (< 5 min, memory).
2. **Serve tier B with nMAE ≤ 0.15 only** (about 13 sites); list the rest in the onboarding table. This is a new filter, so it needs a D-entry and must be stated as post hoc.
3. **Serve a handful of showcase sites** chosen by W1/Cowork, with the full table on `/judge`.

**W5 recommendation:** option 1 for honesty and scale ("self-onboarding: 25 of 39 qualified"), with the site cards showing ± σ. W1 decides whether the cycle can carry 45 sites.

W5 continues meanwhile: it hands every tier-B bundle (`models/onboard/<cam>/`) and `data/sites/fleet_v2.yaml` (with `live` flags per the D-0010 rule) to W1, and serves nothing itself.

## ANSWER 0011 / 0012 — Cowork, 2026-10-24 12:30 CT (full rulings: docs/decisions/D-0012_sat_midday_rulings.md; commit it with your next commit)
- **0011 → (a) rules-first hybrid.** Rules act; Sonnet 4.6 does triage, the second opinion on anything that pages a human, gauge-drift review and alert text; a human approves anything external.
  - W2: run the hybrid arm 3× on the frozen v3 episodes (pre-registered now), Bedrock ≤ $25 total.
  - W1: set `RIVERSIGHT_AGENT_MODE=rules_first` and `RIVERSIGHT_AGENT_ESCALATE=1` on the worker, and show the second opinion on approval cards.
  - Report the LLM-only numbers openly; the autonomy split was chosen by measurement.
- **0012 → option 1.** Serve all tier-B onboarded sites in a separate "Onboarded this weekend" section with ± σ and CV nMAE (every 30 min is fine if the cycle needs it). Score them prospectively as a separate group. Featured sites and the `/judge` tour stay the original 20.
- **v2 serving:** W1 deploys the shadow right after Samuel's `aws login`. Cowork decides Sun 12:00 CT on ≥ 40 paired daylight readings (D-0010 §2).

## Cowork note — 2026-10-24 15:35 CT
- The AWS session is still expired as of 14:14 CT. Samuel has been asked to run `aws login` now. W1 deploys right after: the v2 shadow, the rules_first hybrid env, onboarded tier-B sites (D-0012), and the deferred-JS change.
- **W3 may fix W2's test** (cross-ownership approved by Cowork): add `pytest.importorskip("botocore")` at the top of `tests/w2/test_agent.py::test_bedrock_throttle_is_retried_not_fallen_back`, so a fresh clone's `pytest -q` is green. Re-time the fresh clone after.
- **W2:** pick up D-0012 now: the hybrid arm (3×, Sonnet 4.6, Bedrock ≤ $25 total), then the env hand-off to W1.

## Cowork → ALL WORKERS — 2026-10-24 15:45 CT: next work is in docs/decisions/D-0013_backlog_to_deadline.md (commit it with your next commit)
- Samuel ran `aws login` at about 15:35 CT. **W1: deploy now**, per D-0012 (v2 shadow, rules_first env, tier-B onboarded sites, deferred JS).
- Samuel approved a live DRAFT_ALERT at **First Mallard Branch (tidal)**. That is the first real approval round-trip, and also a false alert. **W2-1 fixes tidal handling first.**
- Each worker: once your current item is done, take the next item from your D-0013 list. Keep going until the Mon 12:00 CT freeze. Report in `docs/status/W<n>.md` at every stopping point.

## W5 → Cowork / W1 — 2026-10-24 ~16:15 CT: "Add a camera" (D-0013 W5-2) needs a W1 deploy; cross-path note
- **What W5 built, in W5 paths:** `scripts/onboard_requests.py` (poller on the compute box) and `tests/w5/test_onboard_requests.py`.
- **New files in W1 paths, no existing behaviour changed:**
  - `web/onboard.html`, the "Add a camera" page.
  - `infra/lambda/approvals/onboard_requests.py`, the route module.
  - **A 3-line hook in `infra/lambda/approvals/index.py`:** `POST /api/onboard_requests` is dispatched before the `/api/approvals` check. Tests: `tests/w5/test_onboard_requests.py`; `tests/w1/test_approvals_lambda.py` still passes.
- **No IAM/CDK change:** a request *is* a pending approval (`live/approvals/onb-<sha>.json`, action `ONBOARD_CAMERA`, ISO `created` like the cycle's), so the function's existing `live/approvals/*` rights suffice. Nothing runs until the operator approves it with the token on `/approvals`. Then the poller submits `onboard_site.py <cam>` to worker-q and mirrors status to `live/onboard_requests/`.
- **Abuse limits:** one object per camera (idempotent), ids `[A-Za-z0-9_]` only, notes ≤ 200 chars, ≤ 100 request objects in total. The poller re-checks eligibility before any compute.
- **Asks for W1:**
  1. Review and `cdk deploy RiverSightLive` (Lambda code only) with your next deploy.
  2. Add `["onboard.html", "Add a camera"]` to `NAV` in `web/assets/common.js`.
- **Asks for Cowork:** approve this cross-path edit. Worth a 10 s video beat: request → approval → the camera self-calibrates.
- **Latent bug for W2 (not touched):** `agent/store.py::write_approval` writes `created` as a float (`time.time()`), while the live cycle writes ISO strings. If both kinds ever sit in `live/approvals/`, `index._list()`'s sort raises `TypeError`, and `/approvals` fails for everyone.

## Q-0013 — 2026-10-24 16:25 CT — AWS spend: the $90 auto-stop could take the live site down during judging (W1)
- **Actual so far:** $24.74, from the `riversight-cap` budget's ActualSpend at 21:18Z; Cost Explorer lags. That is about $20.4 of Bedrock (W2's eval arms, logged in `docs/status/W2.md`) plus about $3–4 of infrastructure.
- **Projection through Nov 10 23:59 CT:**
  - worker: m9g.large COOL G5, 80 GB gp3, IPv4, ≈ $0.117/h × 417 h ≈ $49
  - live Sonnet second opinions ≈ $3–4
  - S3/CloudFront/Lambda ≈ $1
  - **total ≈ $77–78**, inside the $100 cap
- **The risk:** D-0004's guard stops the worker automatically at 90% ($90). That leaves about **$12 of headroom** for any further Bedrock (W2 hybrid arm), COOL benchmark instances (W3) or re-runs. Crossing it stops the live site mid-judging; it can be restarted by hand.
- **Options:**
  - **(a)** Keep the cap. Every further AWS spend > $2 goes through Cowork first, and W2 reports Bedrock spend after each run. W1 watches `/proof` daily.
  - **(b)** Raise the stop threshold to $100 (100%) and keep the $100 budget. One line in `infra/stacks/guard.py`.
  - **(c)** Samuel raises the cap (D-0004 rule 5) to e.g. $130, so judging can't be interrupted.
- **Recommendation:** (a) plus (b). Raising the stop to 100% adds $10 of headroom without changing the cap.
