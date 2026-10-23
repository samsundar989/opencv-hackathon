# River Steward — agent evaluation

Episode set: `results/agent_eval/episodes.jsonl`, sha256 `e12e0f2953533f1f0d911073eea6acdc593ea4653aedee3545f13daddf59f2ac` (frozen 2026-10-23T19:42:31+00:00, git f2706e97f); 78 single-camera episodes (48 real) + 12 fleet cycles. Expected actions were written by `scripts/agent_build_episodes.py` before any arm ran. Every number below is computed by `scripts/agent_eval.py report` from `results/agent_eval/runs/*.jsonl`.

Arms: **rules** = deterministic policy (`agent/rules.py`); **haiku** = Bedrock Claude Haiku 5.5 agent with the OpenCV tools; **haiku_noev** = the same agent whose tools return only the reading's flags (no OpenCV evidence); **sonnet** = the agent on Claude Sonnet 5.5. Each arm ran every episode 3×; cells show mean over repeats (min–max across repeats).

## Headline

| arm | task success | real episodes | synthetic | false-action rate on clean controls | unneeded escalations / episode | fleet top-1 | fleet Kendall τ | LLM fallbacks | p50 / p95 latency (s) | tokens / episode | $ / episode (est.) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| rules | 89.7% (89.7%–89.7%) | 93.8% (93.8%–93.8%) | 83.3% (83.3%–83.3%) | 0.0% (0.0%–0.0%) | 0.00 | 41.7% (41.7%–41.7%) | 0.67 | 0/234 | 1.5 / 18.3 | 0 | 0.0000 |

## Task success by episode kind

| kind | source | n | rules |
|---|---|---|---|
| control_disagree | real | 5 | 100% |
| control_rise | real | 4 | 100% |
| control_view | real | 8 | 100% |
| disagree_camfault | synthetic | 4 | 75% |
| gauge_drift | synthetic | 3 | 0% |
| gauge_flatline | synthetic | 2 | 100% |
| gauge_offset | synthetic | 4 | 75% |
| reanchor_banked | real | 10 | 100% |
| reg_loss_onset | real | 4 | 100% |
| reg_loss_persist | real | 8 | 100% |
| rise_alert | real | 8 | 62% |
| rise_minor | real | 1 | 100% |
| stale_camera | synthetic | 5 | 100% |
| stale_night | synthetic | 3 | 100% |
| view_shift | synthetic | 3 | 100% |
| view_transient | synthetic | 6 | 100% |

## Detection in cycles (real registration loss)

Onset = the first flagged cycle of a real registration-loss segment; persistent = the previous two readings were already flagged. Detection = QUARANTINE in that cycle; escalation = recalibration ticket.

| arm | quarantined at onset | ticket at onset (premature) | quarantined when persistent | ticket when persistent |
|---|---|---|---|---|
| rules | 100% | 0% | 100% | 100% |

## Failure cases

**rules** — 8 episodes failed at least once:

- `disagree_camfault-TX_Buffalo_Bayou_at_Stat-20261009T1700` (3/3 repeats): did `NOOP`, missing `QUARANTINE`. *fresh camera estimate agrees with the gauge (-0.06 ft, σ 0.41) low-quality frame; the quality gate already suppresses it*
- `gauge_drift-IL_Salt_Creek_at_Wood_Da-20261007T1600` (3/3 repeats): did `QUARANTINE`, missing `OPEN_TICKET`, forbidden `QUARANTINE`, wrong args. *camera differs by -1.28 ft with a normal-looking gauge; trusting the gauge, camera quarantined*
- `gauge_drift-NJ_Stony_Brook_at_Prince-20261008T1900` (3/3 repeats): did `QUARANTINE`, missing `OPEN_TICKET`, forbidden `QUARANTINE`, wrong args. *camera differs by -1.11 ft with a normal-looking gauge; trusting the gauge, camera quarantined*
- `gauge_drift-TX_Buffalo_Bayou_at_Stat-20261009T1800` (3/3 repeats): did `QUARANTINE`, missing `OPEN_TICKET`, forbidden `QUARANTINE`, wrong args. *camera differs by -1.10 ft with a normal-looking gauge; trusting the gauge, camera quarantined*
- `gauge_offset-NJ_Big_Brook_near_Marlbo-20261007T2100` (3/3 repeats): did `QUARANTINE`, missing `OPEN_TICKET`, forbidden `QUARANTINE`, wrong args. *camera fault: frame does not register; readings quarantined*
- `rise_alert-CA_First_Mallard_Branch_-20261006T1615` (3/3 repeats): did `DENSIFY`, missing `DRAFT_ALERT`. *rising (+1.39 ft/h) but 26.465 ft is below the site p90 27.852; sampling densified*
- `rise_alert-NJ_Big_Brook_near_Marlbo-20261004T1800` (3/3 repeats): did `DENSIFY`, missing `DRAFT_ALERT`. *rise flagged but no current stage from gauge or camera; sampling densified*
- `rise_alert-TX_Tenmile_Ck_at_Parkins-20261004T2300` (3/3 repeats): did `DENSIFY`, missing `DRAFT_ALERT`. *rising (+0.36 ft/h) but 6.561 ft is below the site p90 6.58; sampling densified*

## Notes

- Costs are estimates at Anthropic first-party list prices (Haiku 5.5 $0.10/$0.50, Sonnet 5.5 $2/$10 per MTok); Bedrock bills its own rates. Latency = model time + original (uncached) tool compute time.
- Temperature is not set: Claude 5.5 models reject non-default sampling parameters, so repeats show the spread.
- Real episodes use cached USGS HIVIS frames and gauge records; synthetic faults are labelled `synthetic` (`agent/faults.py`, `tools.apply_gauge_fault`). No real gauge outage > 3 h exists in the 20 sites' history, so all gauge-stale episodes are synthetic dropouts on real frames.
- Tools use protocol-cut site bundles (training < 2026-10-03), so test-window frames are out-of-sample for the scene model. Test-day frames serve here only as agent inputs; nothing in the stage model was refit or tuned on them.
- `rise_*` labels are hindsight: an alert is expected iff the gauge reached the site's calibration p90 within 6 h.
