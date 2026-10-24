# RiverSight — plan to the deadline and beyond (Cowork, Fri 2026-10-23 16:20 CT)

**Deadline:** Mon Oct 26, 11:45 pm PDT = Tue 01:45 CT. We keep improving until the last safe moment.
- **Submission v1** goes in **Mon 18:00 CT** as insurance.
- Devpost allows edits until the deadline, so improvements keep landing on the live site and in the repo. Re-submit or edit the text by **Mon 23:30 CT**.
- **Endpoint freeze:** Tue 01:00 CT. Nothing risky after that; judging runs Oct 27–Nov 9.

**Goal:** first overall, plus the Agentic and COOL prizes, with a product that a flood office or USGS could actually use, and that we can ship days after the competition.

## Workers (each owns its paths; status in `docs/status/W<n>.md`)
| | scope | contract |
|---|---|---|
| W1 | cloud, live cycle, dashboard, prospective scoring | SPRINT_W1 + D-0009 + D-0010 §1 + the additions below |
| W2 | River Steward agent + evaluation | SPRINT_W2 + D-0009 + the additions below |
| W3 | report, COOL, docs, video assets, number checks | SPRINT_W3 + D-0009 + the additions below |
| **W4 (new)** | model v2: DINOv2 in `cv2.dnn` + seasonal robustness | `docs/slices/SPRINT_W4_MODEL_V2.md` |
| **W5 (new)** | onboarding pipeline (+20–40 sites) + real gauge-outage evidence | `docs/slices/SPRINT_W5_FLEET_ONBOARDING.md` |

## Rubric-driven backlog (after the D-0009 must-fixes), ranked by points per hour

### Technical execution (30)
1. **W1:** prospective live evaluation (D-0010 §1). Truly forward-in-time evidence that accrues on its own. This is our strongest new number.
2. **W4:** model v2 + a seasonal-drift ablation. It attacks our largest known error source (0.38 ft year-long).
3. **W3:** registration ablation table in the report: ORB vs ALIKED+LightGlue vs the reference bank, per site, from committed files.
4. **W1:** cycle robustness. Retries, partial failure isolation (one site never blocks the others), memory ceiling (it was OOM-killed on c8g.medium), structured logs.

### Innovation (20)
1. **W1+W2: "forecast flood picture".** For sites with an NWS NWPS forecast point, draw the forecast crest's wet area into today's frame on the site page, with time-to-crest. The agent already renders it for alerts; make it visible to judges without a flood. If no site has a forecast in range, the slider plus "flood stage" markers (NWS action/minor/moderate/major thresholds, drawn as slider ticks) gives the same effect.
2. **W2: fleet triage view** on the dashboard: "which cameras need a human now", ranked, each with its reason and the OpenCV evidence behind it.

### Real-world impact (20)
1. **W5:** real gauge outages bridged by the camera (Part B). This turns "useful" from a claim into evidence.
2. **W5:** self-onboarding plus the few-shot curve and cost per camera to cover all ~880 cameras.
3. **Samuel:** send the drafted note to the USGS HIVIS team (hivis@usgs.gov) once the URL is live. Any reply is impact evidence; even without one, the report can say the team was contacted. Optional: a Texas county flood office.
4. **W3:** "Users and decisions" section with three concrete personas (county emergency manager, NWS forecaster, USGS hydrographer). For each: what they see, what decision it supports, and what it does not replace.

### User experience (10)
1. **W1:** D-0009 items 2–4 (night fallback, no CDN, featured sites).
2. **W1:** a plain-language "why this status?" tooltip on every pill.
3. **W1:** keyboard-operable slider; contrast AA; alt text on frames.
4. **W1:** load under 2 s on 4G (thumbnails, lazy loading).
5. **W1:** a Lighthouse pass, with the scores in `docs/status/W1.md`.

### Documentation and presentation (10)
1. **W3:** report v2 Sat, final Sun noon (PDF); a README that a judge understands in 60 s.
2. **Cowork:** video script final Sat 20:00 CT after Gate G2; Samuel records Sun morning; target 3:15.
3. **Cowork:** Devpost text drafted Sat night; Samuel pastes it Sun.

### Cloud delivery, reproducibility and responsible operation (10)
1. **W1:** COOL G5 worker live, with `/proof` (instance-identity document, build info, AMI id).
2. **W1:** uptime alarm plus a status line on `/judge` ("last cycle N min ago").
3. **W1:** budget guard verified, with actual spend shown on `/proof`.
4. **W1:** WAF (or the CloudFront flat-rate plan's included protections) in front of the approvals API; least-privilege review.
5. **W3:** `docs/RUNBOOK.md`: what to do if the worker dies, USGS is down or Bedrock throttles, plus the tear-down.

### Agentic Vision prize
**W2:** LLM arms (D-0009 D1) + the no-OpenCV counterfactual + a live approval round-trip + the triage view. Model fallback per Q-0010.

### Best Use of COOL prize
**W3:** an honest per-kernel and end-to-end A/B on the same m9g; $ per camera-month for the full fleet; a scaling curve.
- **W1+W3 (optional, only if time allows):** batch the fleet cycle so COOL-accelerated kernels (resize, cvtColor, Sobel, warpPerspective) run over a whole batch of frames. This is the setting where COOL can actually show a speedup.

## Gates
| when (CT) | gate | owner |
|---|---|---|
| Fri 20:00 | **G1:** live URL on Graviton (stock or COOL), all must-fix items 1–3 deployed | W1 |
| Sat 12:00 | COOL A/B run (or its fallback); W5 pipeline on 3 sites; W2 LLM pilot done | W3, W5, W2 |
| Sat 18:00 | **G2:** feature complete for the video (forecast picture, triage view, prospective tile, agent results); W4 CV result | all |
| Sat 20:00 | Cowork judge-eye audit (desktop and phone, day and night views) + final video script | Cowork |
| Sun 10:00 | Samuel records the video | Samuel |
| Sun 12:00 | v2 decision (D-0010 §2); fleet expansion batch live; report final PDF | Cowork, W4, W5, W3 |
| Sun 18:00 | Devpost page complete (draft saved); full fresh-clone repro + number check green | Samuel, W3 |
| Mon 12:00 | code freeze for anything risky; docs and copy may continue | all |
| Mon 18:00 | **submit v1**; repo public (after the secrets re-scan, Samuel's decision) | Samuel |
| Mon 23:30 | last edits to Devpost text/video link | Samuel |

## After the deadline: ship plan (what "actually useful" needs)
1. **All ~880 gauged HIVIS cameras** through the W5 pipeline, with nightly incremental fetch and weekly refit.
2. **Public API:** per-camera JSON feed, plus webhooks for flood-state changes and gauge-outage gap-fill.
3. **Night/IR model** per site, and a combined camera+gauge Kalman estimate as the product output.
4. **Ungauged transfer research:** survey-light calibration from a few staff-plate reads, or a neighbouring gauge.
5. **Partnerships:** USGS HIVIS, NWS forecast offices, county flood-warning systems. An open benchmark manifest (image URLs + labels + splits) on HIVIS.
6. **Ops:** multi-AZ worker, SLOs, cost dashboard. Target under $0.10 per camera-month at fleet scale (W3's COOL numbers will tell).
