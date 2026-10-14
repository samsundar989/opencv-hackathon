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
