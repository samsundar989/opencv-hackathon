# D-0008 — 2026-10-22 — Final-sprint rulings (Cowork for Samuel); answers Q-0007

## Samuel (Oct 22, 13:00 CT)
- RiverSight is now the **top-priority project**; arc-whest and RSNA are done.
  - RiverSight jobs may use worker-q at **high** priority, non-preemptible. This supersedes the low-priority part of D-0005; the submit form is otherwise unchanged.
  - The local 5090, remaining RunPod credits and Kaggle quota may be used when needed. Log RunPod spend.
- **As many Claude Code workers as useful.** Three run in parallel: W1 Cloud, W2 Agent, W3 Eval/COOL/Docs (`docs/PLAN_2026-10-22_FINAL_SPRINT.md`).
- Samuel records the video whenever we're ready. The target is Sat evening or Sun morning.

## Cowork rulings
1. **No pivot.** The kill test passed, and anything new would start from zero with 4.5 days left.
   - **One direct rival appeared on Oct 20: StageSight** (`docs/research/2026-10-22_rivals.md`). It reads the staff plate on one USGS camera — Hancock, also our site — with RMSE 0.26 ft on one flood and 2.4% frame coverage, plus a Bedrock agent, human approval and COOL.
   - **Our differentiators:** a 20-camera fleet; no plate or survey; high coverage; flood-height maps; fleet-level agent triage.
   - We add a fair Hancock head-to-head, bootstrap CIs, a coverage table and a "not claimed" section (W3 §4b), plus repeated multi-model agent evaluation (W2).
   - **Never claim** "first camera stage on HIVIS". **Do claim** "the first fleet-scale, plate-free, survey-free system", which stays true.
2. **AWS:** one always-on Graviton worker plus CloudFront/S3/Lambda/SNS/Bedrock through Nov 10, within the $100 cap (D-0004).
   - **COOL G5 AMI on m9g.large** for the live worker and the benchmark. The Marketplace subscription is Samuel's explicit click (Cowork asks in chat).
   - The stock arm64 + pip 5.0.0.93 setup is the fallback.
   - Any single action expected to cost > $10 still goes through `Q-`.
3. **Product claim** (from Q-0007 findings). These, not live replacement of the gauge:
   - gauge-outage gap-fill (beats last-known value at 72 h for 15/20 sites, 7 d for 18/20)
   - flood state
   - camera QA: view change, lens, disagreement
   - "see what's under water at stage X" via the flood-height map

   Say plainly that the camera does not beat 15-minute persistence while the gauge is online.
4. **Q-0007.1 — demo images:** keep them committed. They are derived overlays of public-domain USGS frames, face-blurred. Non-negotiable 7 covers raw frames and bulk redistribution, not illustrative overlays. Add an image-credit line ("USGS HIVIS, public domain") to the README and the dashboard.
5. **Q-0007.2 — next slice:** replaced by the sprint contracts.
   - The D-0007 setting stays frozen for all reported numbers.
   - Live models may be refit on all data up to export (INTERFACES §1). Label them "live models" and never mix their numbers into the frozen results.
   - View-change detection and re-anchoring become W1 flags plus W2 agent behavior 1.
6. **Repo access for judges.** The recommendation is to make the GitHub repo public at submission (Mon Oct 26), after W3 runs a full-history secrets scan (`gitleaks` or `trufflehog`) on Sat. **Samuel confirms before it goes public.** Making it public can't really be undone. The alternative is adding the judges as collaborators.
