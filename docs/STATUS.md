# STATUS (newest first)

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
