# Fri Oct 23, round 2: two new sessions (W4, W5) + one add-on message for each running session

## W5 — Fleet onboarding + real outages (start a NEW session)
You are **W5 (Fleet onboarding + real-outage evidence)** for RiverSight, our OpenCV AI Competition 2026 entry. The deadline is Mon Oct 26, 11:45 pm PDT. We push until the end.
1. `git pull`. Read, in order:
   - `docs/PLAN_2026-10-23_TO_THE_END.md`
   - `docs/decisions/D-0010_prospective_eval_and_v2_governance.md`
   - `docs/slices/SPRINT_W5_FLEET_ONBOARDING.md`
   - `CLAUDE.md`
2. First commit, `[W5] start + cowork plan`: commit Cowork's untracked files:
   - `docs/PLAN_2026-10-23_TO_THE_END.md`
   - `docs/decisions/D-0010_*.md`
   - `docs/slices/SPRINT_W4_*.md`
   - `docs/slices/SPRINT_W5_*.md`
   - `NEXT_PROMPTS_2026-10-23b.md`
   - `docs/OUTREACH_DRAFT.md`

   Append a D-0010 summary to `docs/DECISIONS.md`, and create `docs/status/W5.md`.
3. Execute SPRINT_W5. worker-q at **high** priority; ≤ 4 concurrent USGS requests; use the API key. Only touch your paths. `git pull --rebase` before each push.

## W4 — Model v2 (start a NEW session after W5's first commit)
You are **W4 (Model v2: DINOv2 in cv2.dnn + seasonal robustness)** for RiverSight, our OpenCV AI Competition 2026 entry. The deadline is Mon Oct 26, 11:45 pm PDT.
1. `git pull`. Read, in order:
   - `docs/PLAN_2026-10-23_TO_THE_END.md`
   - `docs/decisions/D-0010_prospective_eval_and_v2_governance.md` (§2 governs you)
   - `docs/slices/SPRINT_W4_MODEL_V2.md`
   - D-0007
   - `CLAUDE.md`
2. Create `docs/status/W4.md`. Execute SPRINT_W4. Never recompute or replace the frozen kill-test numbers. Torch is allowed on the 5090 (a `.venv` for the export only). worker-q at high priority.

## Add-on for the running W1 session
Read `docs/PLAN_2026-10-23_TO_THE_END.md` and `docs/decisions/D-0010_prospective_eval_and_v2_governance.md` §1. **Before the first live reading is served**, record the frozen live-model hashes (`results/live_prospective/frozen_models.json`) and add `scripts/score_prospective.py` plus the `/judge` tile.

Then, after the D-0009 must-fixes, work through the W1 items in the plan's rubric backlog:
1. forecast flood picture with NWS flood-category ticks on the slider
2. "why this status?" tooltips
3. accessibility and Lighthouse
4. uptime status line
5. spend on `/proof`
6. approvals API protection

Add a `shadow_stage_ft` field for W4's v2 bundles and onboard W5's sites as their bundles arrive (tier A/B only).

## Add-on for the running W2 session
Read `docs/PLAN_2026-10-23_TO_THE_END.md`. On top of D-0009, build the **fleet triage view** data: `live/agent/triage.json`, ranked cameras needing a human, each with its reason and the OpenCV evidence. W1 renders it.

For Q-0010:
- if Samuel has accepted the Claude 5.5 agreements, run the D1 arms on 5.5;
- if not by Sat 10:00 CT, use the Haiku 4.5 + Sonnet 4.6 fallback you described.

## Add-on for the running W3 session
Read `docs/PLAN_2026-10-23_TO_THE_END.md`. On top of D-0009, add:
- the registration ablation table
- a "Users and decisions" section (3 personas)
- `docs/RUNBOOK.md`
- the prospective-live and real-outage sections in report v2 (fed by W1 and W5)
- a "Model v2 (candidate)" subsection (fed by W4)

The COOL A/B now runs on the real G5 AMI, since Samuel subscribed.
