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
