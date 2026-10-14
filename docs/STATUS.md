# STATUS (newest first)

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
