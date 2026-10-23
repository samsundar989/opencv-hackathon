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
