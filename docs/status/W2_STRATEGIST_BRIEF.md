# W2 River Steward: brief for the strategist (Sat 2026-10-24, ~01:30 CT)

**One line:** The agent evaluation is final. The deterministic OpenCV-evidence policy (93.9 %) beats Claude Sonnet 4.6 (71.4 %) and Claude Haiku 4.5 (58.8 %), and the live site currently lets Haiku decide. That is **Q-0011**, and it's the one decision W2 needs. The approval round-trip still needs Samuel's token.

## 1. Acceptance (SPRINT_W2 + D-0009 + D-0011), as of now

| item | status | evidence |
|---|---|---|
| `handle()` / `rules.handle()` keep the INTERFACES signatures; every behaviour has a test | **done** | `tests/w2/`: 38 tests, all green |
| ≥ 60 episodes, expected actions written first, hash before the final arms | **done** | v3: 98 single-camera (63 real), 26 clean controls, 12 fleet cycles; `FROZEN.json` git `47b1298` |
| 3 arms × 3 repeats, 2 LLM models | **done** | rules 3×, Claude Haiku 4.5 3×, Haiku flags-only 3×, Claude Sonnet 4.6 1× (per ANSWER 0010). Opus 4.5 dropped on budget |
| D-0009: out-of-range + muddy-water behaviour, with episodes | **done** | 20 episodes (Hancock/Pecatonica floods, Animas live); rules 20/20 |
| ≥ 2 real floods through the full loop + timeline image | **done (rules)** | 3 floods through W1's `live.cycle.replay`; `results/agent_eval/replay/` |
| Kill switch, token cap, audit log on the live stack | **done** | `results/agent_eval/live_demo/` |
| Fleet triage view data | **done** | `live/agent/triage.json`, written by W1's cycle every run |
| D-0011: connected-inundation overlay | **done** | `render_wet_overlay` uses W1's `wet_connected` |
| `summary.json` for `/judge` | **done** | `results/agent_eval/summary.json` (+ `LLM_ANALYSIS.md`) |
| One real approval round-trip, screenshotted | **blocked on Samuel** | token only he has. Approve Animas `apr-20261023-1a09d4dc90` on `/approvals` (W1 fixed the id bug at 401fbed) |

## 2. Numbers we can quote (all from `results/agent_eval/summary.json`)

| arm | task success | false actions, clean controls | fleet top-1 | est. $ |
|---|---|---|---|---|
| rules (same OpenCV tools) | **93.9 %** | 0.0 % | 91.7 % | 0 |
| Claude Sonnet 4.6 | 71.4 % | 3.8 % | **100 %** | 5.13 |
| Claude Haiku 4.5 | 58.8 % (56.1–61.2) | 7.7 % | 44.4 % | 4.33 |
| Claude Haiku 4.5, flags only | 51.4 % (49.0–55.1) | 15.4 % | 52.8 % | 4.13 |

**OpenCV-evidence effect** (paired, Haiku with tools minus flags only):
- **Overall:** +7.5 points, **95 % CI −1.4 to +16.3**. Not significant overall.
- **Decisive where the action depends on the image:**
  - re-anchoring: +73, and 0 % without registration evidence
  - muddy-water gap-fill: +89
  - night gap-fill: +44
  - false actions on clean controls halve
- **Negative** on a stuck gauge (−83).

**Flood replays** (models trained before each flood): the alert is drafted in the first cycle the gauge crosses p90, at all three floods.

## 3. What to claim, and what not to

**Claim:**
- OpenCV evidence drives the actions. The rules policy is 100 % tool evidence.
- Measured lifts where image facts matter (above).
- Human approval for every alert and ticket, with kill switch and token cap demonstrated live.
- Honest multi-model evaluation, with failure modes published.

**Don't claim:**
- "The LLM agent beats rules", or any average OpenCV-evidence gain. The CI crosses 0.
- Any Claude 5.5 model.
- That the camera measures above its calibrated range: it saturates, and the agent then trusts the gauge.
- Real gauge outages. Those episodes are synthetic dropouts on real frames.

**Integrity trail** (good for the report): `runs_v1/README.md` and `POST_FREEZE_CHANGES.md`. Three label/bug corrections before any LLM arm, the OOM incident, and the parser fix after the arms.

## 4. Decisions needed

- **Q-0011 (W2's recommendation: option a).** Rules take the actions. Sonnet 4.6 ranks the fleet, second-opinions anything that pages a human, and reviews gauge drift.
  - **Ready now:** `RIVERSIGHT_AGENT_MODE=rules_first` + `RIVERSIGHT_AGENT_ESCALATE=1` on the worker, which is W1's env.
  - **Cost:** about $0.05 per paging decision.
- **Video:** the Hancock timeline and the Salt Creek alert overlay are ready. Use the `/approvals` screenshot once Samuel approves.

## 5. Spend and incidents

- **Bedrock ≈ $20.4** (final arms $13.6, lost OOM runs $6.01, pilots $0.81), under the $25 ceiling.
- **OOM incident** (Fri ~21:30 CT): W2's eval jobs committed 31–40 GiB each and the host crashed.
  - **Fixed:** one shared ALIKED/LightGlue per process.
  - **Measured:** 1.9 GiB peak, 74/74 tool outputs identical.
  - The live worker gets the same fix when W1 redeploys.
