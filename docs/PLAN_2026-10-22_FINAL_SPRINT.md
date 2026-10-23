# RiverSight — final sprint plan (Cowork, Thu 2026-10-22 13:00 CT)

**Hard deadline:** Devpost, **Mon Oct 26 11:45 pm PDT = Tue Oct 27 01:45 CT**.
**Our submit target:** **Mon Oct 26 18:00 CT**.
**Code freeze:** Mon Oct 26 12:00 CT. After that, docs only.
**Judging:** Oct 27 – Nov 9. The endpoint stays up the whole time.

## Where we are
- **The core works.** Kill test v2 PASSED on Oct 15, with frozen test days scored once:
  - P1: 14/20 sites accurate
  - P2: 15/16 event sites beat a 24-hour-stale gauge
  - P3: 95.7% registration
  - median MAE 0.18 ft
  - flood-height maps and event GIFs exist
- **Honest caveats** (from D-0002 and Q-0007):
  - The camera never beats 15-minute persistence while the gauge is online.
  - Year-long CV gives 0.38 ft median, because seasons drift.
  - 7 of 20 cameras changed view within 12 months.
- **The product claim follows from these:**
  - **gap-fill when the gauge is down:** beats a 72 h last-known value at 15/20 sites and 7 d at 18/20
  - **flood state**
  - **camera QA:** view changes, lens problems, gauge disagreement
  - **"see the flood in the picture":** the flood-height map
- **Nothing is deployed yet.** No AWS resources, agent, dashboard, COOL, report, video or Devpost page.

## Rivals (Oct 22 sweep: `docs/research/2026-10-22_rivals.md`)
- **StageSight (Oct 20) is now in our lane.** It reads the staff plate on one USGS NIMS camera (Hancock, also our site).
  - RMSE 0.26 ft on one flood, numbers for 2.4% of frames.
  - Has a Bedrock agent with approvals and SNS, a live Lambda URL and a LaTeX report. No video or Devpost page yet.
  - **We win on breadth** (20 cameras, no plate, high coverage, flood-height maps, fleet triage) **if we match its rigor**: bootstrap CIs, Hancock head-to-head, repeated multi-model agent evaluation. These are added to W2 and W3.
- **Overall leaders:** PlumeRank (finished; 3:34 video; live) and DEPTH (very active, no live link or video yet).
- **Strong agentic entries:** AutoScope and Breathing Room.
- **COOL:** everyone who measured it found it roughly flat end to end (0.97–1.04×). Honest per-kernel + end-to-end + $ is the standard.
- **Field size:** 5,475 participants; ~250 Devpost projects tagged "opencv 5 aws"; the gallery is still hidden.

## Samuel's rulings today
- RiverSight is now the top-priority project. Arc-whest and RSNA are done.
- worker-q and the 5090 are ours. RunPod and Kaggle can be used if needed.
- As many Claude Code workers as useful.
- Video: Samuel records whenever we're ready.
- AWS: the $100 cap (D-0004) still applies. The always-on live site plus COOL fits under it (see D-0008).

## Strategy: what wins (rubric: Technical 30 · Innovation 20 · Impact 20 · UX 10 · Docs 10 · Cloud 10, plus $1k COOL and $1k Agentic)
1. **Live, always-on judge site.** The first screen shows real USGS cameras right now:
   - a camera stage ± σ next to the gauge
   - a "what's under water at this stage" overlay
   - status flags
   - an agent decision log
   - a `/judge` page with the frozen-test numbers, failure cases and reproduce commands
2. **Evaluation rigor that matches the leaders:** frozen constants plus hashes, and the test read once (done). Add the agent fault-injection eval and the COOL A/B, each with a baseline.
3. **A real agent loop in which OpenCV output changes the action** (needed for the Agentic prize). Four behaviors:
   - view change → re-anchor or quarantine
   - gauge outage → camera gap-fill marked provisional
   - disagreement → camera-fault vs gauge-suspect ticket
   - rise → densify sampling, render the wet overlay at the forecast crest, draft an alert that a human approves
4. **COOL runs the live worker on Graviton.** Benchmark it honestly against stock pip OpenCV 5.0.0.93 on the same instance. Our features use COOL-accelerated ops: resize, cvtColor, Sobel, warpPerspective.
5. **A short, sharp video and report.** Demo in the first 30 seconds. Honest about the limits.

**Scope cuts (do not build):**
- night models
- staff-plate OCR
- seg net or SAM
- discharge
- more than 20 calibrated sites (expansion is an optional stretch for W3 after Sat 12:00 CT)
- Step Functions (approvals go through S3 + a Lambda URL)
- Strands (plain Bedrock Converse tool-use is enough)

## Workers (each one owns its paths; touches only them plus its own status file)

| worker | owns | contract |
|---|---|---|
| **W1 Cloud** | `infra/`, `src/riversight/live/`, `web/`, `scripts/export_site_models.py`, `scripts/deploy*` | `docs/slices/SPRINT_W1_CLOUD.md` |
| **W2 Agent** | `src/riversight/agent/`, `scripts/agent_*.py`, `results/agent_eval/` | `docs/slices/SPRINT_W2_AGENT.md` |
| **W3 Eval + COOL + Docs** | `bench/`, `results/cool_bench/`, `report/`, `docs/{ARCHITECTURE,OPENCV5_USAGE,RESPONSIBLE_USE,PRIOR_ART,COOL_BENCHMARK,REPRODUCE}.md`, `README.md`, `CLAUDE.md` description | `docs/slices/SPRINT_W3_EVAL_DOCS_COOL.md` |
| **Cowork** | review, video script, Devpost copy, judge-eye audits, `docs/PLAN_*`, `docs/decisions/` | — |

**Shared rules:**
- Interfaces live in `docs/INTERFACES.md`.
- Each worker writes `docs/status/W<n>.md`, newest first, at every stopping point.
- Workers don't edit `docs/STATUS.md`; Cowork rolls it up.
- `docs/DECISIONS.md` and `docs/HUMAN.md` are append-only. Run `git pull --rebase` before every append and commit.
- Commit prefixes: `[W1]`, `[W2]`, `[W3]`.
- Push small commits often, and always `git pull --rebase` before pushing.
- `pytest -q` green before pushing. Each worker adds tests under `tests/<w>/`.

## Timeline (CT) with gates
| when | W1 Cloud | W2 Agent | W3 Eval/COOL/Docs | Samuel |
|---|---|---|---|---|
| **Thu 22 PM–night** | budget guard (D-0004) first; export site bundles; `live.cycle` runs locally on all 20 sites end to end; CDK skeleton | tools + rules policy + Bedrock loop working locally on recorded readings; episode builder (real view changes from history + synthetic faults) | README/CLAUDE refresh; architecture diagram v1; OPENCV5_USAGE update; COOL bench harness runs locally (pip arm) | `aws login --profile riversight`, check it works; Bedrock model access confirmed |
| **Fri 23** | **Gate G1, 18:00:** live site on CloudFront, worker on Graviton (COOL AMI if subscribed, else stock arm64), cycling every 30 min | agent wired into the live cycle; approval page plus SNS email to Samuel; first ≥40-episode eval | report draft v1 (sections from protocol and kill-test numbers); COOL A/B on m9g, same instance type as live, using a short-lived bench instance that the script terminates | approve the COOL subscription when asked |
| **Sat 24** | dashboard polish (UX 10 pts), `/judge`, `/proof`, CloudWatch dashboard and alarms, fresh-clone deploy timing | agent eval final + ablations (rules-only, no-OpenCV-evidence), real event replay through the full loop | failure gallery, responsible use, prior art, report v2, timed fresh-clone repro | — |
| **Sat 24 evening** | **Gate G2: feature freeze.** Cowork judge-eye audit. | | | — |
| **Sun 25** | bug fixes only | bug fixes only | report final (PDF), Devpost text (Cowork drafts) | **record the video** (Cowork script; ~3:15) |
| **Mon 26** | 12:00 code freeze; uptime monitor | — | final numbers check: every number in the docs traced to a results file | **submit by 18:00 CT**; make the repo public, or add the judges |

If G1 slips past Sat 12:00, cut the COOL prize work before cutting the agent.

## Platform facts (checked Oct 22; `scratchpad J_platform_oct22`, copied to `docs/research/2026-10-22_platform.md`)
- **OpenCV 5.1 is not released.** PyPI's latest 5.x is still 5.0.0.93 (abi3, with aarch64 wheels, so it installs on CPython 3.14). **Keep the pin.**
- **Use the COOL G5 AMI** (`prodview-igdweaoo6prb6`, "COOL Graviton 5-1.0").
  - It has Python 3.12/3.13/**3.14** venvs and runs on **m9g (Graviton5, GA in us-east-2)**. m9g.large costs about $0.005/h for COOL on top of EC2. The listing says it is built on "OpenCV 5.1.0" (probably a dev build): record `cv2.__version__` and `getBuildInformation()` as evidence.
  - The G4 AMI (5.0, c8g) and the Docker image top out at Python 3.12. They are the fallback only.
- **Bedrock in us-east-2:** Claude Haiku/Sonnet 5.5 work only through the cross-region IDs `us.anthropic.claude-haiku-5-5…`. Use those.
- **Always-on endpoint.** The organizers never answered the cold-start question on the forum, so keep the endpoint always on.
- **CloudFront flat-rate Free plan** can now be set up through CDK and API (since Sep 3).

## Risks and mitigations
- **COOL G5 build may differ from our 5.0 pin** (5.1 API differences, missing ALIKED/LightGlue/DNN pieces).
  - W1 checks on day 1 with a ≈$0 test: launch m9g.large from the G5 AMI, import, `getBuildInformation`, run one full cycle, terminate.
  - If COOL lacks something, the worker runs registration with stock pip and COOL does the classical feature path. Document the hybrid honestly.
  - Guard DNN engine enums with `hasattr`.
- **KleidiCV arm64 bugs** (#29794 resize INTER_LINEAR 3-channel segfault; #29816 warpPerspective + BORDER_REPLICATE). Use INTER_AREA everywhere on arm and test on Graviton before G1.
- **USGS rate limits.** Use the OGC key quota of 1,000 req/h plus legacy IV batching. 20 sites × 2/h is trivial.
- **Bedrock quota or access.**
  - The rules policy is the fallback, and the agent eval reports both.
  - Haiku 5.5 is the default; enforce a daily token cap in code.
- **Spend.** The D-0004 guard must be live before any EC2 launch.
  - One c8g.medium or large always-on: about $30–55 through Nov 10.
  - Bench instances are short-lived, and the script terminates them.
  - Report actual spend in `docs/status/W1.md` daily.
- **Merge conflicts between workers.** Disjoint paths, the interfaces doc, rebase before push.
