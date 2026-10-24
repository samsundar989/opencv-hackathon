# D-0012 — 2026-10-24 (Sat 12:30 CT) — Midday rulings: Q-0011, Q-0012, v2 decision path, framing of the agent, COOL and prospective results (Cowork)

## State (from the repo)
| item | result |
|---|---|
| Live site | Up on COOL G5 / m9g, 0 cycle errors through the host crash. |
| Prospective live | Median AE **0.221 ft** on the first 51 scored readings. A 24 h last-known gauge value wins while rivers are steady (0/13 sites). That was pre-registered as a possible outcome, and it gets reported. |
| COOL A/B | **Flat end to end (1.0067×), bit-identical outputs.** ORB registration 1.16–1.21×. DNN is about 98% of stage time. One m9g covers about 880 cameras at 15 min. |
| Agent eval, frozen v3 | Rules **93.9%** · Sonnet 4.6 **71.4%** · Haiku 4.5 **58.8%** · Haiku without OpenCV evidence **51.4%** (evidence effect +7.5 pts, CI includes 0). |
| Model v2 (DINOv2 in `cv2.dnn`) | Year-long CV **0.252 vs 0.380 ft (−33.7%)**, 19/20 sites better. Criterion 1 met. |
| W5 | 40/40 sites onboarded, 30 tier B, **$0.054 per camera**. Few-shot curve plateaus at about 30 days. Outage catalogue: 3,734 outages at 61% of reporting gauges. Real-gap wins are partial. |
| Report | v2 + PDF done. |

**Blocker:** the AWS session expired overnight, since `aws login` lasts 12 h. Samuel must re-login before W1 can deploy the v2 shadow and the backlog. This now recurs daily: Samuel logs in at about 09:00 and 21:00 CT through Monday.

## Q-0011 → option (a): the rules-first hybrid ("appropriate autonomy, chosen by measurement")
- **Live, the deterministic OpenCV-evidence policy takes the actions** that are reversible or that page a human. Claude Sonnet 4.6:
  1. ranks the fleet (`triage.json`);
  2. gives a recorded second opinion on every decision that pages a human, which goes on the approval card;
  3. reviews gauge-drift/offset suspicions, where it beat the rules 67% to 0%;
  4. drafts the human-facing alert and ticket text.

  A human approves anything external. Haiku 4.5 no longer decides live.
- **Framing in the report, `/judge` and the video.** We tested whether an LLM should drive. Measured on 98 frozen episodes, it shouldn't take actions alone (71.4% / 58.8% vs 93.9% for rules), but it adds value where the rules are blind (drift 67% vs 0%; fleet triage 12/12). So the autonomy split was set by evidence: the LLM advises, OpenCV-grounded rules act, and a human approves. This *is* the Agentic Vision rubric's "appropriate autonomy" and "failure handling / human control". **Do not hide the 58.8% / 71.4%.**
- **W2:** ship `RIVERSIGHT_AGENT_MODE=rules_first` + `RIVERSIGHT_AGENT_ESCALATE=1` to W1. Evaluate the hybrid arm on the frozen v3 episodes, 3× with Sonnet 4.6. The policy is defined now, before the run, so the arm is pre-registered. Report it beside the other arms, and keep total Bedrock ≤ $25.
- **W1:** add the env vars to the worker. Show the Sonnet second opinion on approval cards and the triage panel.

## Q-0012 → option 1, with a presentation guard
- Serve **all tier-B onboarded sites** per D-0010 §3, in a separate home-page section: **"Onboarded this weekend: self-calibrated from each gauge's history; not part of the frozen test."**
  - Each card shows ± σ and the site's CV nMAE.
  - Featured sites and the `/judge` tour stay the original 20.
- If the cycle can't carry everything within 15 min on the m9g, onboarded sites may run every 30 min.
- Prospective scoring includes them **as a separate group** (`onboarded`), never mixed into the frozen-20 prospective numbers.
- Report and README headline: "self-onboarding: 30 of 40 new cameras qualified (tier B) at $0.054 each in compute; median nMAE 0.136; absolute error scales with river size".

## Model v2: serving decision path (D-0010 §2 unchanged)
- W1 deploys the v2 shadow **immediately after Samuel's login**. Criteria 2 (shadow live median AE no worse than v1) and 3 (cycle < 5 min) are assessed by Cowork **Sun 12:00 CT** on paired daylight readings. A decision needs **≥ 40 paired readings**.
- If fewer than 40 exist, or any criterion fails, v1 keeps serving and v2 is reported as "candidate + shadow".
- If all pass, v2 serves from Sun afternoon. The prospective record keeps scoring the frozen v1 bundles as pre-registered, with v2 alongside.
- **The v2 result belongs in the video and the README as a candidate result.** The 0.38 → 0.25 ft year-long improvement directly answers "what about seasonal drift?".

## COOL framing (W3)
Honest and specific:
- COOL is flat end to end on our workload because 98% of the time is DNN, which COOL doesn't accelerate. It speeds up the classical registration path by 1.16–1.21× with bit-identical outputs.
- At fleet scale one m9g.large covers all ~880 gauged HIVIS cameras at 15-minute cadence for about **$0.06 per camera-month**.

Add the Amdahl chart. Lead with fleet $/camera-month and provenance, not speedup.

## Prospective framing (W1/W3)
Show it as it is: median AE, % within 0.25 ft, coverage, and the fact that the 24 h last-known gauge value beats the camera in calm weather. Pair it with the gap-fill and real-outage results, which is when the camera matters.

## Samuel (today)
1. **`aws login --profile riversight` now**, and again tonight at about 21:00 CT.
2. **Approve the pending Animas alert** on the live `/approvals` page, using the operator token in `.env`. W1 or W2 can tell you where it is. Take a screenshot or let the worker capture it: this is the human-approval moment for the video.
3. **Video:** recording Sun at about 10:00 CT. Cowork sends the final script Sat evening.
