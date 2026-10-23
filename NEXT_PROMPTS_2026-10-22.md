# Final sprint: three Claude Code sessions (open each one in `C:\Users\samsu\Documents\opencv-hackathon`)

Paste one block into each session. Start **W1 first**, wait for its first commit (about 5 min), then start W2 and W3.

---

## W1 — Cloud

You are **W1 (Cloud)** for RiverSight, our OpenCV AI Competition 2026 entry. The deadline is Mon Oct 26, 11:45 pm PDT, and Gate G1 is **Fri Oct 23 18:00 CT**.

1. `git pull`. Then read, in order:
   - `docs/PLAN_2026-10-22_FINAL_SPRINT.md`
   - `docs/decisions/D-0008_sprint_rulings.md`
   - `docs/INTERFACES.md`
   - `docs/slices/SPRINT_W1_CLOUD.md`
   - `CLAUDE.md`
2. First commit (`[W1] sprint start`) does four things:
   - commit the untracked Cowork sprint files:
     - `NEXT_PROMPTS_2026-10-22.md`
     - `docs/PLAN_2026-10-22_FINAL_SPRINT.md`
     - `docs/INTERFACES.md`
     - `docs/VIDEO_SCRIPT_DRAFT.md`
     - `docs/decisions/D-0008_sprint_rulings.md`
     - `docs/research/2026-10-22_{platform,rivals}.md`
     - `docs/slices/SPRINT_W{1,2,3}_*.md`
   - append D-0008 to `docs/DECISIONS.md`
   - create `docs/status/W1.md`
   - add stub `src/riversight/agent/__init__.py` + `agent/rules.py` with the INTERFACES §3 signatures, so W2 can replace the bodies. **Commit only the stub;** W2 owns that folder afterwards.

   Push.
3. Execute SPRINT_W1_CLOUD end to end. The **budget guard comes before any EC2 launch.** RiverSight jobs go through worker-q at **high** priority, non-preemptible (D-0008).
   - When you need the COOL G5 AMI subscription, or any action expected to cost > $10, write a `Q-` in `docs/HUMAN.md`, tell Samuel in this chat, and continue on something else.
4. Update `docs/status/W1.md` at every stopping point. Only touch the paths you own. `git pull --rebase` before each push.

---

## W2 — Agent

You are **W2 (Agent: River Steward)** for RiverSight, our OpenCV AI Competition 2026 entry. The deadline is Mon Oct 26, 11:45 pm PDT.

1. `git pull`. Then read, in order:
   - `docs/PLAN_2026-10-22_FINAL_SPRINT.md`
   - `docs/decisions/D-0008_sprint_rulings.md`
   - `docs/INTERFACES.md`
   - `docs/slices/SPRINT_W2_AGENT.md`
   - `CLAUDE.md`
2. Create `docs/status/W2.md`. You own `src/riversight/agent/`; W1 committed a stub there, so replace its bodies but keep the signatures.
3. Execute SPRINT_W2_AGENT:
   - Use Bedrock Converse with the cross-region profile `us.anthropic.claude-haiku-5-5…` in us-east-2 (`AWS_PROFILE=riversight`).
   - Write the rules policy first, so there's always a fallback.
   - Write expected actions before running episodes, and hash the episode set before the final arms.
   - Batch replays go through worker-q at high priority.
4. Update `docs/status/W2.md` at every stopping point. Only touch your paths. `git pull --rebase` before each push.

---

## W3 — Eval, COOL, Docs

You are **W3 (Eval/COOL/Docs)** for RiverSight, our OpenCV AI Competition 2026 entry. The deadline is Mon Oct 26, 11:45 pm PDT.

1. `git pull`. Then read, in order:
   - `docs/PLAN_2026-10-22_FINAL_SPRINT.md`
   - `docs/decisions/D-0008_sprint_rulings.md`
   - `docs/INTERFACES.md`
   - `docs/slices/SPRINT_W3_EVAL_DOCS_COOL.md`
   - `results/kill_test_v2.md`
   - `CLAUDE.md`
2. Create `docs/status/W3.md`. Start with §1: rewrite the README and the CLAUDE.md description, then commit.
3. Continue SPRINT_W3 in order:
   - architecture diagram
   - OPENCV5_USAGE
   - COOL bench harness, run locally on the pip arm first; the AWS run waits for the COOL subscription (W1 or Samuel)
   - report v1 Fri, v2 Sat, final Sun noon
   - failure gallery
   - repro docs
   - Sat: secrets scan

   Never type a number into a doc that isn't in a committed results file.
4. Update `docs/status/W3.md` at every stopping point. Only touch your paths. `git pull --rebase` before each push.
