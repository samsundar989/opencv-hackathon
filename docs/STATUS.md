# STATUS (newest first)

## 2026-10-14 (night CT) — SLICE_01B under way: gate passed, history fetch running (Claude Code)
- Cowork review committed (`6d765b9`): D-0006 appended to DECISIONS. My earlier stage-source entry, which also used the number D-0006, is renumbered **D-0005a** (it was referenced nowhere else). `docs/AWS_ACCOUNT_NOTES.md` and `_xfer/` gitignored; `_xfer/` (2.2 GB of transfer tarballs) deleted.
- **Step 1 gate PASSED** (`ebb1178`). New modules: `vision/scene_features.py`, `calib/flood_height_map.py`, `calib/scene_regressor.py`, `eval/protocol_v2.py`, plus 14 synthetic unit tests. Fit20 CV with our own ALIKED+LightGlue registration over the 17 shared sites: scene-ridge median MAE **0.278 ft** (Cowork 0.249, +0.029); water-block **0.238** (Cowork 0.220, +0.018). Both are inside ±0.05. 8/17 sites ≤ 0.25 ft (Cowork 9/17). Source: `results/scene/gate_fit20.csv`. Remaining gap: we register 30-min frames to a different reference, and our sun-based night filter drops dusk frames.
  - Caveat: Cowork's water-block number skips folds with < 20 ROI blocks (e.g. Cowhouse 0.045 vs 0.33 with all frames predicted). The production regressor falls back to all blocks and predicts every frame.
- **Step 2:**
  - NIMS archives are patchy. Spot checks: Animas has no frames before ~summer 2026; Tenmile covers 52/52 weeks of the 12-month window. Coverage per site goes to `results/history/coverage_*.csv`.
  - The first fetch job (2896) died because (a) the OGC key quota was exhausted (429, retry-after 27 min) and (b) the legacy NWIS IV fallback now 301-redirects to `nwis.waterservices.usgs.gov`. Fixed with a test; history stage now comes from legacy IV (identical values, D-0005a). Retry is job **2898**.
- Ready, not yet run:
  - `scripts/history_pass.py`: registration with piecewise references + features.
  - `scripts/scene_tune.py`: forward-chaining monthly CV, 36 settings.
  - `scripts/scene_score.py`: one-shot scoring, guarded by a frozen-config hash and refusing a second run; its `--dry-run` was exercised on the fit window and caught a dtype bug.
  - `scripts/scene_demo.py`: flood-height JPGs, plus an event GIF written by `cv2.imwriteanimation`, with YuNet face blur via `cv2.FaceDetectorYN`. `face_detection_yunet_2023mar.onnx` was downloaded from opencv_zoo into `models/onnx/` (gitignored).
- Compute: jobs 2876 (features, 1 min), 2896 (failed), 2898 (queued), all at low priority. No RunPod/Kaggle/AWS spend.

## 2026-10-14 (afternoon CT) — SLICE_01: registration PASS, waterline FAIL-likely; paused for direction (Claude Code)
- All 20 sites fetched, registered and hand-transected (`data/sites/<cam>/transects.yaml`, placed from fit-window frames only).
- **Registration (acceptance #1): 95.7%** of 9,000 true-daylight frames (≥90% required) — `results/kill_test/registration_summary.csv`. ORB alone ≈40%; ALIKED+LightGlue rescued 4,892; sun-elevation QA caught 1,593 floodlit night frames; geometric QA rejected 210.
- **Waterline→stage (fit-window blocked CV, test days untouched):** MAE ≤ 0.25 ft at 1/20; beats constant-median at 4/20; beats persistence-24h at 4/20 — `results/kill_test/fit_window_cv.csv`. Kill test as specified would FAIL.
- Test days **not scored**. Q-0005 (protocol) and Q-0006 (direction: recommend pulling the seg-net detector forward + 90-day calibration, re-run once on the same frozen test days) are open in `docs/HUMAN.md`.
- Compute: all image passes via worker-q at `low` (jobs 2814, 2820, 2822, 2826, 2835); 2 preemptions by arc-whest, no losses (per-site caches). No RunPod/Kaggle/AWS spend.

## 2026-10-14 (late morning CT) — SLICE_01 in progress; recovered from a machine crash (Claude Code)
- **Crash:** the box went down while RAM was ~7 GiB free (arc-whest jobs + my direct dev runs). After restart: git clean and pushed (`85b8347`), worker-q HEALTHY, image cache intact (0 partial files). From now on every image pass — dev iterations included — goes through worker-q at `low` priority (`scripts/kill_test.py --dev --only <site>`); only unit tests, single-image probes and network fetches run directly. RunPod/Kaggle remain the overflow path (no spend so far).
- **Data:** 20 kill-test sites (`data/sites/kill_test.yaml`), 30 days ending 2026-10-14T00Z, ~24k 720-px frames cached under `data/raw/720/`, 0 download errors.
- **Bug found:** `fetch_sites.py` never saved `stage.parquet` (frames.parquet had stage; persistence baseline and the runner need the series). Fixed; rerunning the fetch (images cached) — waiting out a USGS rate limit politely.
- **Registration:** ORB→ALIKED+LightGlue cascade. Evidence so far: Tenmile Ck 375/375 daytime frames with ALIKED (ORB alone ≈48%); Brandywine 755/755 (754 ORB, 1 ALIKED).
- **Detector status (fit window only):** Tenmile CV shows the hard part — fit days are mostly flat base flow (5.24–6.62 ft) and detections on the first transect design were noisy. Changes: transects now cut across the *boundary* of stage-correlated regions; projective fit constrained to have no pole inside the stage range, affine fallback for short ranges. Not yet evaluated on all sites.
- **Next:** registration batch for 20 sites via worker-q → `--dev` CV pass (fit window) → one full run that scores the test days → `results/kill_test.md` + D-0002.

## 2026-10-14 — SLICE_01 setup (Claude Code)
- **Environment:** Python 3.14.4 (global, `pythoncore-3.14-64`), `opencv-python-headless==5.0.0.93` (`cv2.__version__` = 5.0.0), numpy 2.4.6. `python -m pip install -e ".[dev]"` OK; `pytest -q` → 15 passed. Note: bare `pip` on this box points at a Python 3.11 Store install — always use `python -m pip`.
- **torch:** not installed in the global 3.14 env (Q-0002 updated). Not needed for SLICE_01; needed from SLICE_03.
- **USGS API key:** present in `.env` (gitignored). It had been pasted into tracked `.env.example`; moved to `.env` before any commit, placeholder restored (never pushed).
- **worker-q:** D-0005; `.gpuq.toml` added. RiverSight runs at `low` priority behind RSNA knee + arc-whest (Samuel, Oct 14).
- `docs/AWS_ACCOUNT_NOTES.md` left **uncommitted** on purpose (account IDs, card last-4; repo will be judge-visible) — see Q-0004.

## 2026-10-13 23:xx UTC — bootstrap (Cowork)
- Repo bootstrapped by Cowork: rules (`CLAUDE.md`), plan, slice contracts, verified data clients, geometry core, classical vision core, 15 passing tests (run in a Linux container against `opencv-python-headless==5.0.0.93`; not yet run on Samuel's Windows box).
- GitHub private repo created: `samsundar989/opencv-hackathon` (empty; first push pending).
- Samuel's to-dos: `docs/AWS_SETUP.md` (AWS account tonight), USGS API key, Slack, Devpost project.
- Open questions: see `docs/HUMAN.md` Q-0001..Q-0003.
- Next: Claude Code runs `BOOTSTRAP_PROMPT.md` → SLICE_01 kill test by Oct 14 night.

### Checklist (Samuel)
- [ ] AWS account created on the **Paid plan** (or upgraded) — `docs/AWS_SETUP.md` A
- [ ] Root MFA; IAM user `riversight-admin`; `aws configure` done; `aws sts get-caller-identity` works — B
- [ ] Budget $150 with alerts — C
- [ ] Bedrock access requested (Claude Haiku 5.5 / Sonnet 5.5, Nova 2 Lite) — D
- [ ] EC2 vCPU quota request (32) — E
- [ ] USGS API key in `.env` — G16
- [ ] Slack #opencvcomp26 joined — G17
- [ ] Devpost project created — G18
- [ ] (Oct 17–18) COOL Graviton4 AMI subscribed — F
