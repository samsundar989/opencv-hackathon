# SPRINT W2 — River Steward: the fleet agent (Agentic Vision prize + core product)

**Owner:** Claude Code session "W2". **Commit prefix:** `[W2]`. **Status file:** `docs/status/W2.md`.
**Owns:** `src/riversight/agent/`, `scripts/agent_*.py`, `results/agent_eval/`, `tests/w2/`.
**Read first:** `docs/PLAN_2026-10-22_FINAL_SPRINT.md`, `docs/INTERFACES.md` §3–5, and the Agentic Vision rubric in `docs/research/competition-briefing.md` (or the project briefing §2).

## Why this matters
The prize rubric is OpenCV 5 + agent integration 30 · orchestration and appropriate autonomy 25 · task effectiveness and evaluation 20 · failure handling, observability, security and human control 15 · UX/docs/demo 10. **The rule: an OpenCV result must change a later plan, tool call, action or approval request.** A chatbot that explains a fixed result does not count.

## Design
- **Model and transport:** plain Bedrock Converse tool-use via boto3.
  - Model `us.anthropic.claude-haiku-5-5…`, a cross-region inference profile. Haiku/Sonnet 5.5 are not callable in-region in us-east-2.
  - Sonnet 5.5 only for an escalated second opinion, behind a flag.
  - No Strands, no Step Functions.
- **Budgets:** max 8 tool calls per event, temperature 0, a daily token cap in code, and a cost estimate logged per decision.
- **Tools:** the OpenCV tools listed in INTERFACES §4, implemented over the existing modules (`vision/register.py`, `vision/scene_features.py`, `calib/*`).
  - Every tool returns compact JSON plus a one-line summary.
  - Images are never sent to the LLM; it gets numbers and summaries only. That's both a privacy point and a cost point.
- **Deterministic rules policy (`agent/rules.py`):** the same actions from hand-written thresholds. It is (a) the fallback when Bedrock fails and (b) the eval baseline.
- **Behaviors**, triggered by W1 flags. The agent chooses tools and actions:
  1. **VIEW_CHANGE**
     - Tools: `compare_to_last_good` (phaseCorrelate shift, similarity), `image_quality` (fog, glare, IR), `reregister_fullres` against the reference bank.
     - Actions: transient (fog, rain, IR, spider) → `NOOP`/retry next frame; matches a banked reference → `SET_REFERENCE`; persistent new view → `QUARANTINE` + `OPEN_TICKET` (human recalibration).
  2. **GAUGE_STALE**
     - Tools: `estimate_stage` + `image_quality`.
     - Actions: `MARK_PROVISIONAL` (camera-only gap-fill with σ) + `DENSIFY`. If the camera isn't trustworthy (night or low quality), say so and fall back to the last known value.
  3. **DISAGREE**
     - Tools: quality checks, re-registration, `get_gauge` trend, and an upstream or neighbor gauge if available.
     - Actions: camera fault → `QUARANTINE`; gauge suspect (camera is confident and consistent, gauge flat or jumping) → `OPEN_TICKET` "gauge suspect" for human review.
  4. **RISING / flood state**
     - Tools: `DENSIFY` (sample every 15 min), `get_nws_forecast` (NWPS), `render_wet_overlay` at the current and forecast-crest stage.
     - Actions: `DRAFT_ALERT` with both overlays → **human approval** → SNS email.
- **Human control.** Only reversible actions are autonomous; external actions need approval.
  - Kill switch: an S3 flag `live/agent/ENABLED=false` makes the agent no-op.
  - Every decision is logged with tool traces, per INTERFACES §3.

## Evaluation (`scripts/agent_eval.py` → `results/agent_eval/`)
- **≥ 60 episodes**, at least half real:
  - **Real view changes:** the 7 cameras with history segment changes (`data/derived/<cam>/history/segments.csv`).
  - **Real rise events:** the 15 event sites.
  - **Real gauge gaps:** if any appear in the history.
  - **Synthetic, labelled as such:** camera shift (random homography 2–8% of the frame), lens occlusion/fog (Gaussian blur + haze + droplets), IR night frames, gauge dropout (mask 6–72 h), gauge offset/drift (+0.5 ft step).
  - Each episode has `expected_actions` written **before** running.
- **Metrics:**
  - task success: correct primary action
  - false-action rate on clean controls (≥ 15 no-fault episodes)
  - escalations per episode
  - time-to-detect in cycles
  - p50/p95 latency, tokens and $/episode
- **Arms:**
  - (a) LLM agent
  - (b) rules-only
  - (c) LLM agent **without OpenCV evidence**: tools return only the flags. This is the counterfactual showing that OpenCV output drives the decisions.
- **Real event replay through the full loop:** at least 2 floods (Pecatonica and Salt Creek have GIFs already). Save a decision timeline image per event for the video.
- **Repeat every arm 3× per episode**, and run the LLM arm on **two models** (Haiku 5.5 and Sonnet 5.5). Report mean ± spread. The rival StageSight did 3× per model, so that is now the expected bar.
- **Lean into what a single-camera agent can't do.** Fleet-level triage, i.e. ranking which cameras need a human first; seasonal drift detection leading to a recalibration proposal; re-anchoring after a view change. Include ≥ 10 fleet-level episodes (several sites flagged in the same cycle).
- Write `results/agent_eval/REPORT.md` with tables, failure cases and costs, and freeze the episode set by hash before running the final arms.

## Milestones
- **Thu night:** tools + rules + LLM loop run locally on recorded Readings; episode builder done.
- **Fri 18:00:** wired into the W1 live cycle (same signature as the stub); approvals path works end to end (pending item → token approve → SNS email); first eval run.
- **Sat 18:00:** final eval with all 3 arms; event replays; REPORT.md.

## Acceptance
- [ ] `riversight.agent.handle()` and `rules.handle()` match the INTERFACES signatures; tests cover each behavior with a canned Reading.
- [ ] Live: decisions appear in `live/agent/*.jsonl` and on the dashboard; one real approval round-trip demonstrated (screenshot for the video).
- [ ] ≥ 60 episodes, 3 arms, `results/agent_eval/{episodes.jsonl,results.csv,REPORT.md}`; episode-set hash recorded before the final run.
- [ ] Kill switch, token cap and audit log demonstrated.
