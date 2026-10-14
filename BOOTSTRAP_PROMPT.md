# First Claude Code prompt (paste this into Claude Code opened in C:\Users\samsu\Documents\opencv-hackathon)

You are the builder for RiverSight, our entry in the OpenCV AI Competition 2026 (deadline Oct 26). Read `CLAUDE.md`, then `docs/PLAN_2026-10-13_RIVERSIGHT.md`, then `docs/slices/SLICE_01_INGEST_KILL_TEST.md`, then `docs/DATA_SOURCES.md`. Skim `docs/research/competition-briefing.md` for competition facts.

Do these in order, committing as you go (small commits, prefix `[S01]`):

1. **Git:** `git init -b main`, add everything, commit "bootstrap: plan, slice contracts, data clients, geometry + vision core, tests", `git remote add origin https://github.com/samsundar989/opencv-hackathon.git`, `git push -u origin main`. (Repo exists, private, empty.)
2. **Environment:** use the latest globally installed Python (Samuel's instruction). `pip install -e ".[dev]"`. Confirm `python -c "import cv2; print(cv2.__version__)"` prints `5.0.0` and `pytest` is green (15 tests). Record Python/torch/CUDA versions in `docs/STATUS.md` (see `docs/HUMAN.md` Q-0002). If `.env` has no `USGS_API_KEY`, proceed at low rate (≤2 requests/s) and leave Q-0003 open.
3. **workerq:** read the docs in `C:\Users\samsu\Documents\gpu-queue` (or wherever workerq lives) and write the current GPU job submit command into `docs/DECISIONS.md` as D-0003. No GPU job is needed in SLICE_01.
4. **SLICE_01:** execute the contract end to end — catalog, 20-site selection with reasons, 30-day fetch (≤4 parallel downloads, cached), transects, registration, waterline, projective fit, temporal-split evaluation, `results/kill_test.md` with the per-site table and overlays, `D-0002` PASS/FAIL. Iterate on the classical detector on **fit-window** frames only; never tune on the 10 test days. Target: done by the evening of Oct 14 (Chicago). Update `docs/STATUS.md` at every stopping point so Cowork and Samuel can see progress.
5. If SLICE_01 passes, continue straight into `docs/slices/SLICE_02_REGISTRATION_STAGE_V1.md` without waiting.

Rules you must not break: pin `opencv-python-headless==5.0.0.93`; no fabricated numbers; no secrets in the repo; be gentle with USGS APIs; write questions to `docs/HUMAN.md` and keep working on something else rather than stopping.
