# W2 River Steward: brief for the strategist (Fri 2026-10-23, ~16:45 CT)

**One line:** The agent is fully built and evaluated offline, and the rules baseline is final. The prize-deciding evidence still needs Bedrock, which needs `aws login`. That evidence is LLM-with-OpenCV versus LLM-without-OpenCV. Once Samuel logs in, the remaining arms take about 2 hours to run.

## 1. Acceptance (SPRINT_W2), as of now

| item | status | evidence |
|---|---|---|
| `handle()` / `rules.handle()` keep the INTERFACES signatures; every behaviour has a test | **done** | `src/riversight/agent/`; `tests/w2/` has 32 tests and the full suite is green |
| ≥ 60 episodes, expected actions written first, hash before the final arms | **done** | 78 single-camera episodes (48 real), 26 clean controls, 12 fleet cycles; `results/agent_eval/FROZEN.json` (episodes sha `e12e0f29…`) |
| 3 arms × 3 repeats, 2 LLM models | **1 of 4 arms run** | the rules arm is final. Haiku, Haiku-without-OpenCV and Sonnet are blocked on `aws login` (Q-0008) |
| ≥ 2 real floods replayed through the full loop, plus a timeline image | **done (rules policy)** | 3 floods through W1's `live.cycle.replay`; `results/agent_eval/replay/` |
| Live decisions in `live/agent/*.jsonl` and on the dashboard; one real approval round-trip, screenshotted | **not started** | needs W1's G1 deploy, which is also blocked on `aws login` |
| Kill switch, token cap and audit log demonstrated | **unit-tested only** | still needs a live demo once deployed |

## 2. Numbers we can quote today (all from committed files)

Source: `results/agent_eval/REPORT.md` (generated from `results/agent_eval/runs/rules.jsonl`).

**Rules baseline, frozen set, 3 repeats (identical, because the policy is deterministic):**
- Task success **92.3 %**: real episodes 97.9 %, synthetic 83.3 %.
- False actions on the 26 clean controls: **0**.
- Unneeded escalations: **0**.
- Fleet triage: top-1 66.7 %, Kendall τ 0.83.
- Latency p50 / p95: 1.2 / 15.2 s. This is tool compute; re-registering against up to 12 references drives the p95.

**Rules failures, all honest:**
- Gauge drift: 0 of 3. The rules have no drift test, by design. This is the headroom an LLM can show.
- 1 gauge offset.
- 1 synthetic camera fault too mild to show in the image.
- 1 rise just under the site p90.
- Every fleet-triage miss inherits one of these per-event misses.

**Flood replays** (models cut 3 days before each rise, so out-of-sample). The alert was drafted **in the first cycle the gauge crossed the site p90** at all three:

| flood | rise |
|---|---|
| Salt Creek, Jul 3 | +4.9 ft |
| Pecatonica, Apr 14 | +3.8 ft |
| Hancock, Jul 29 | +8.8 ft (StageSight's site) |

## 3. What not to claim yet

- **Any LLM-agent number.** None exists yet.
- **"OpenCV output drives the decisions."** We can't claim this as measured until the no-OpenCV arm (c) runs. The design does support saying "the agent can't decide without OpenCV evidence", and the rules policy depends on tool outputs.
- **"Real gauge outages."** None over 3 h exists in the 20 site histories. Every gauge-stale episode is a synthetic dropout on a real frame, and is labelled synthetic.
- **"Real camera view changes."** Say **"real registration loss"** instead. Spot checks found Big Brook and White Rock re-aimed, but Pecatonica is the same view after a strong seasonal change.
- **"The camera tracks big floods."** Above its calibrated range the camera saturates: Hancock reads about 10 ft against an 18 ft gauge. The agent handles this correctly by trusting the gauge and quarantining the camera. That's the story; camera accuracy in floods is not.
- **Re-anchoring diversity.** Re-anchoring was tested on 10 real episodes, but 8 of them come from one camera (Pecatonica). Salt Creek supplies the other 2.

## 4. Integrity trail (worth a line in the report: it shows rigor, not weakness)

All of these were found by the runs and fixed **before any LLM arm ran**. Each superseded run is kept with a README in `results/agent_eval/runs_v1/`.

1. **v1 episode labels.** Four view episodes trusted the history pipeline's registration flags and turned out wrong. Every real view episode is now re-checked against the exact reference bank it exposes.
2. **Rules bug.** A gauge reading 0 minutes old was treated as missing. Found in the Hancock replay; a regression test now covers it.
3. **Alert spam.** The Hancock replay drafted 40 alerts, one email per 30-minute cycle. A hysteresis guard rail (one alert per site per rise, unless the water is +0.5 ft higher or 12 h have passed) brought it to 4.

## 5. Decisions needed

- **D1: Sonnet arm budget.**
  - Rough estimate for 78 × 3 runs, at Anthropic list price and before measuring: about $15. Bedrock's rate is unknown.
  - That exceeds D-0008's $10 single-action rule.
  - **Recommendation:** run the Haiku arms first (about $1–3). Then run Sonnet **once** over the full set, about $5. The contract asks for 3 runs per arm, and StageSight did 3 per model, so if the bar must be matched, file a Q- for the full 3×.
  - The pilot gives the real figure before anything is committed.
- **D2: add a gauge-drift rule now?**
  - **Recommendation: no.** It would need a re-freeze, and the honest 0 of 3 is the clearest showcase of what an LLM adds over fixed thresholds, provided Haiku gets it.
  - If Haiku also fails, report it as a known limitation.
- **D3: video assets.** Ready to use now:
  - `results/agent_eval/replay/NY_East_Branch_Delaware_River_at_Hancock_Staff_2026-07-28_rules_timeline.png`
  - `results/agent_eval/replay/IL_Salt_Creek_at_Wood_Dale_2026-07-03_rules_alert.jpg`

  LLM versions will appear alongside them once Bedrock is up. The live approval screenshot depends on W1's G1.

## 6. Dependencies and timeline after `aws login`

1. **About 15 min.** Pilot of 5 dev episodes: confirm the cross-region model IDs (`us.anthropic.claude-haiku-5-5`, `…sonnet-5-5`), measure tokens and dollars, and check `additionalModelRequestFields` handling. If `llm.py` needs a transport fix, re-freeze; the episodes are unchanged.
2. **About 1–1.5 h on worker-q.** Final arms: Haiku, then Haiku-no-OpenCV, then Sonnet (per D1). LLM flood replays alongside.
3. **About 30 min after W1's G1.** One real approval round-trip, plus kill-switch and token-cap demos on the live stack.

**For W1** (in `docs/status/W2.md`): a QUARANTINE never lifts in the live state, so Hancock stays quarantined after the crest. Suggestion: clear it once registration is OK and camera and gauge agree for N cycles.

**Risk:** if login slips past Sat morning, the LLM arms still fit before G2 (Sat evening), but the approval round-trip depends on W1's deploy the same day.
