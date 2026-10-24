# RiverSight architecture

Sources are Mermaid (`docs/img/*.mmd`); the SVG/PNG next to them are rendered with
`npx -y @mermaid-js/mermaid-cli@11.4.2 -i <name>.mmd -o <name>.svg -b white`.

## System

![RiverSight system architecture](img/architecture.svg)

**Offline calibration** runs once per site on the workstation through worker-q. Up to 12 months of HIVIS frames and the co-located gauge record go through the same registration cascade used live (ORB, then ALIKED + LightGlue, then USAC_MAGSAC homography). Each frame is warped into the reference view and cut into 4 px blocks with Lab and Sobel features. For each block the **flood-height map** learns h*, the stage at which that patch goes under water, plus a reliability score. Reliable blocks form the ROI for a kernel-ridge regressor, and a causal Kalman filter smooths its output. The setting is global and frozen (D-0007). The result is a **site bundle** (`reference.jpg`, `scene_model.npz`, `meta.json`; `docs/INTERFACES.md` §1) uploaded to S3.

**Live cycle** runs every 15 min on one Graviton EC2 worker (m9g.large, COOL OpenCV build; stock arm64 + pip OpenCV 5.0.0.93 is the fallback). For each site it takes the newest NIMS frame, skips night, registers, computes the stage ± σ, pulls the gauge, computes image-quality metrics and flags, draws the wet-area overlay (every block with h* ≤ the estimated stage), blurs faces with YuNet, and writes a Reading (§2) plus overlay to S3. CloudWatch gets cycle time, flag counts and alarms; a budget guard stops EC2 before the $100 cap (D-0004).

**Front door.** CloudFront serves the static dashboard and the live JSON from S3: the site map, per-site pages with a "what's under water at X ft" slider, `/judge` (frozen-test numbers, failure cases, reproduce commands), `/proof` (the COOL build provenance the worker records) and `/approvals`. Approvals go through a Lambda Function URL that writes back to S3. Everything Regional is in us-east-2.

## Agent loop (River Steward)

![River Steward agent loop](img/agent_loop.svg)

The agent is only called for **flagged** readings, so a quiet day costs nothing in LLM calls. It is plain Bedrock Converse tool use (Claude Haiku 5.5 through the `us.` inference profile) with at most 8 tool calls per event at temperature 0. The tools are OpenCV functions over the site bundle and frames (`docs/INTERFACES.md` §4). The LLM gets numbers and one-line summaries, **never images**. If Bedrock fails or the daily token cap is hit, a deterministic rules policy makes the decision; it is also the evaluation baseline.

What OpenCV output changes:

| flag (from the live cycle) | OpenCV evidence the agent gathers | action |
|---|---|---|
| `VIEW_CHANGE` | phaseCorrelate shift and structure similarity vs the last good frame; full-resolution re-registration against the reference bank; fog/glare/IR scores | transient → `NOOP`; matches a banked reference → `SET_REFERENCE`; new view → `QUARANTINE` + `OPEN_TICKET` |
| `GAUGE_STALE` | stage ± σ from the scene model, image quality | `MARK_PROVISIONAL` (camera gap-fill) + `DENSIFY`; untrustworthy camera → fall back to last known value |
| `DISAGREE` | quality, re-registration, gauge trend | camera fault → `QUARANTINE`; gauge suspect → `OPEN_TICKET` |
| `RISING` | NWS forecast crest, wet overlay rendered at the current and the crest stage | `DENSIFY` + `DRAFT_ALERT` |

**Human control.** `SET_REFERENCE`, `QUARANTINE`, `DENSIFY` and `MARK_PROVISIONAL` are reversible and run on their own. `OPEN_TICKET` and `DRAFT_ALERT` always wait for a human, who approves on the dashboard or through the SNS e-mail link. An S3 kill switch (`live/agent/ENABLED`) turns the agent into a no-op. Every decision, with its tool trace, tokens and cost, is appended to `live/agent/YYYY-MM-DD.jsonl`.

## Where each piece lives

| component | code | owner |
|---|---|---|
| registration, features, privacy | `src/riversight/vision/` | — |
| flood-height map, regressor | `src/riversight/calib/` | — |
| site bundle export | `scripts/export_site_models.py` | W1 |
| live cycle | `src/riversight/live/` | W1 |
| CDK stack | `infra/` | W1 |
| dashboard | `web/` | W1 |
| agent, tools, rules | `src/riversight/agent/` | W2 |
| COOL benchmark | `bench/` | W3 |
