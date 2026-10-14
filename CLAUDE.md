# RiverSight — Claude Code operating rules

RiverSight is our entry in the **OpenCV AI Competition 2026 (powered by AWS)**. Deadline **Sun Oct 25 (our internal) / Mon Oct 26, 11:45 pm PDT (hard)**. Goal: **win 1st overall** (+ Best Use of COOL and Agentic Vision if cheap). Read `docs/PLAN_2026-10-13_RIVERSIGHT.md` first, then the active slice in `docs/slices/`.

## What we are building (one paragraph)
The ~880 public USGS HIVIS river webcams that sit next to a USGS stream gauge become self-calibrating water-level instruments: each frame is registered to a per-site reference (OpenCV 5 ALIKED + LightGlue + USAC_MAGSAC), the waterline is found along fixed transects (classical profiles + a small ONNX water-segmentation net in OpenCV 5's new DNN engine), and a per-transect 1-D projective model `u(h) = (a·h + b)/(c·h + 1)` fitted from the gauge's own history maps waterline pixel → stage in feet. A fleet agent (Bedrock + MCP tools, Step Functions human approval) re-anchors drifted cameras, quarantines bad readings, flags suspect gauges, and on rapid rises checks upstream + the NWS forecast, draws the forecast crest onto the live image, and drafts a human-approved alert. Deployed on AWS Graviton with COOL, benchmarked honestly. Evaluated on ~100k auto-labeled image–stage pairs with held-out time and held-out sites.

## Non-negotiables
1. **Pin `opencv-python-headless==5.0.0.93`.** Never float it (5.1 renames DNN engine enums). Never hard-code engine enum integers; use `cv2.dnn.ENGINE_*` names and guard with `hasattr`.
2. **OpenCV 5 must do load-bearing work.** Keep `docs/OPENCV5_USAGE.md` current: every `cv2` call that matters → what it does → what breaks without it. Judges score "depth of OpenCV 5 use" (30 pts).
3. **Never fabricate or round numbers upward.** Every metric in docs comes from a committed results file produced by a committed script. Frozen constants are hashed before any held-out read (`results/constants.sha256`); the held-out set is read once.
4. **Real data only for claims.** Synthetic/fault-injected data is fine for agent tests, labeled as such.
5. **No secrets in the repo.** AWS creds live in `aws configure`; API keys in `.env` (gitignored). Never print secrets.
6. **Respect the data sources.** Be gentle with USGS APIs (≤4 concurrent requests, exponential backoff on 429/5xx, cache everything under `data/raw/`, never re-download what's cached). Get a free USGS API key (`.env: USGS_API_KEY`) and pass it as `api_key=`.
7. **Privacy:** blur faces/plates (YuNet) before any frame leaves the pipeline to an LLM or dashboard. Don't redistribute raw images; the public benchmark is a manifest (image URLs + labels + splits).
8. **Ask, don't guess, on anything irreversible or costly** (AWS spend > $20 per action, deleting data, external messages). Write questions to `docs/HUMAN.md` as `## Q-NNNN` and continue with other work; Samuel answers with `## ANSWER NNNN`.

## Environment (Samuel's Windows box, `sam-mega-pc`)
- Use the **globally installed, latest Python** (Samuel's instruction). `python --version` should be ≥3.12. Install with `pip install -e ".[dev]"`. Only if a dependency conflict appears, create `.venv` with `uv venv` and say so in `docs/STATUS.md`.
- GPU: **RTX 5090** (Blackwell, sm_120). Heavy jobs (SAM2 pseudo-labeling, segmentation training, large batch inference) go through **workerq** — read its docs at `C:\Users\samsu\Documents\gpu-queue` before the first GPU job and record the submit command in `docs/DECISIONS.md`. Light CPU work runs directly.
- **RunPod** credits exist but are limited and shared: use only when the 5090 is busy/insufficient, and log the spend in `docs/STATUS.md`.
- Kaggle GPU quota is a further fallback.
- OpenCV 5's new DNN engine is CPU-only. Train in PyTorch on the GPU → export ONNX → run in `cv2.dnn` (that is the product path on Graviton). Diff every ONNX model against onnxruntime before trusting cv2.dnn output.
- AWS region: **us-east-1**. Credentials via `aws configure` (profile default). Never commit `cdk.out` secrets.

## Repo layout
```
CLAUDE.md                  this file
docs/PLAN_*.md             master plan (Cowork writes; Claude Code executes)
docs/slices/SLICE_NN_*.md  slice contracts: scope, acceptance, deliverables
docs/STATUS.md             running status (Claude Code updates after every work session)
docs/DECISIONS.md          numbered rulings (D-NNNN); append-only
docs/HUMAN.md              questions for Samuel (Q-NNNN) and his answers
docs/research/             competition research (judges, rivals, OpenCV 5, AWS/COOL, prior art)
src/riversight/            package
scripts/                   CLIs (fetch, kill test, eval, bench)
tests/                     pytest
data/                      gitignored; raw/ cache, derived/ parquet, sites/ configs
results/                   committed: eval CSV/JSON, constants hashes, benchmark outputs
infra/                     CDK (Python)
web/                       dashboard SPA
```

## Working loop
- Work slice by slice. Before starting a slice, re-read its contract; when done, mark acceptance items with evidence (file paths, numbers) in `docs/STATUS.md`, commit, push.
- Commit small and often to `main` (solo repo); message prefix `[SNN]` for the slice.
- Tests: `pytest -q` must pass before every push. Add a test with every bug fix.
- Keep a `make`/`invoke`-style entry point: `python -m riversight.cli <cmd>`.
- When a slice's acceptance can't be met, don't quietly lower the bar — write the shortfall in `docs/STATUS.md` and a `Q-` in `docs/HUMAN.md`.

## Competition facts you must not get wrong
- Deadline Oct 26, 11:45 pm PDT (Devpost). Judging Oct 27–Nov 9: the endpoint must stay up. Winners Nov 10.
- Overall rubric: Technical 30 · Innovation 20 · Impact 20 · UX 10 · Docs 10 · Cloud/responsible 10. Specials: COOL $1k, Agentic Vision $1k.
- Required package: technical report, judge-accessible repo, pinned deps + build/deploy/test instructions, architecture diagram, working web endpoint, ≤5-min video showing the team, evaluation evidence incl. failure cases.
- Prior art exists (OTT HydroSight, Tenevia, Eltner 2026, Xu & Wang 2025, USGS RISE dataset, Stevens/CIROH). Our claim is narrow and true: first open, fleet-wide, survey-free, self-calibrating system + first held-out-site benchmark + live endpoint + agentic QA. See `docs/research/prior-art.md`.
