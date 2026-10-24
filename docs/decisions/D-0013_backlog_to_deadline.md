# D-0013 — 2026-10-24 (Sat 15:45 CT) — Backlog to the deadline: make RiverSight solve the root problem, not just demo it (Cowork)

**The root problem.** Stream gauges go dark, drift, ice up and get washed out, often when floods hit. Responders also can't *see* what a number like "12.3 ft" means on the ground. At the same time, about 1,300 public USGS cameras sit unused as instruments, and nobody watches their health.

So RiverSight must deliver four things:
1. **A trustworthy stage estimate when the gauge can't be trusted.**
2. **A picture of where the water is.**
3. **Automatic QA of both instruments** (camera and gauge).
4. **A way for real users to consume it.**

Every item below serves one of these. They are ordered by value per hour, with an owner. Keep shipping in small deploys; nothing risky after the **Mon 12:00 CT** freeze.

Samuel approved a live **DRAFT_ALERT at First Mallard Branch, a tidal site**, at 15:37 CT. That is the first real human-approval round-trip. It also shows a defect, fixed by W2-1 below.

## W2 — agent and QA
1. **Tidal sites (now).**
   - **The problem:** a daily tide must never trigger a flood alert.
   - **Fix:** mark tidal sites in `meta.json` (`tidal: true`; First Mallard, Savannah dock, any onboarded tidal site, detected automatically by a significant 12.42 h / 24.84 h periodicity in the gauge history). For those sites, `RISING` uses the **tidal envelope**: the daily max compared with that site's tidal-max distribution, or the residual after a harmonic fit. It does not use the 3 h rise.
   - Add episodes, re-freeze, rerun the rules arm, and record it as a post-freeze change.
   - The approved First Mallard alert stays in the log as a **documented false alert**, with the fix referenced. That honesty is a feature.
2. **Hybrid arm (D-0012)** 3× on the frozen v3 set; hand `rules_first` env to W1.
3. **Camera-health QA for operators** (USGS has ~1,300 cameras; nobody watches them). A daily fleet health report, `live/agent/health.json`, produced by the agent:
   - camera offline (no upload > 6 h in daylight; Pecatonica has been dark since Oct 20)
   - view changed
   - lens degradation trend (sharpness/fog p-levels drifting over days)
   - IR stuck on during the day
   - gauge suspect (drift/flatline vs camera)

   Each item is a ticket draft with evidence images, and each ticket needs human approval before anything is sent. Evaluate on history: how many real offline/moved/dirty-lens periods it catches across the 60 sites, plus false positives on clean days.

## W1 — product surface
1. **Fused "RiverSight stage" as the headline number on each site.**
   - Gauge when fresh. When stale or flagged, a camera-driven Kalman estimate with growing σ.
   - When `OUT_OF_RANGE`, a lower bound. Show the provenance pill: "gauge", "camera gap-fill", "lower bound".
   - This is the product's output and what a user would consume.
   - **W4 supplies the fusion math;** W1 shows the result.
2. **"Replay a flood" on site pages** (judges will visit when rivers are calm). A button that plays the pre-computed out-of-sample replay (Salt Creek Jul 3, Hancock Jul 29, Pecatonica Apr 14) frame by frame:
   - the wet overlay rising
   - camera vs gauge chart
   - the agent's decisions and the drafted alert appearing in time

   Use W2's replay outputs; precompute assets into S3. **Highest demo value of anything left.**
3. **Public data feed:**
   - `/api/v1/sites.json`, `/api/v1/sites/<cam>/latest.json` and `/history.json` (static S3 JSON via CloudFront)
   - an Atom/RSS feed of flood-state changes and approved alerts
   - `/api.html` docs with an example `curl` and a schema
   - Never send email or webhooks to third parties.
4. **`/health` page** rendering W2's fleet health report.
5. **Onboarded tier-B sites live** (D-0012), plus the v2 shadow and the `rules_first` env, as soon as the deploy is unblocked.

## W4 — core model
1. **v2 shadow decision** data by Sun 12:00 (D-0010 §2 and D-0012).
2. **Fusion math** for W1-1: a 1-D Kalman over [gauge when fresh, camera when not], with process noise from gauge increments and camera noise = site σ (v1/v2). Score the fused estimate on simulated gauge outages over history: 6 h, 24 h, 72 h and 7 d gaps vs last-known value. This is the honest "what a user gets" number.
3. **Online recalibration (shadow only):** a weekly incremental refit that appends new daylight frames + gauge. Show in CV that refitting after a flood extends `stage_max` (the Hancock lesson). Do not change the served model before the deadline unless D-0010-style criteria are met by Mon 09:00.
4. **Night/IR flood state (stretch).** Many HIVIS cameras switch to IR at night. Train a per-site IR flood-state classifier (normal / elevated / flood) on IR frames with gauge labels, forward-chaining CV. Report balanced accuracy vs 24 h persistence. Ship only as a "night flood-state (experimental)" pill if the CV beats persistence at ≥ 60% of sites.

## W5 — scale
1. **Onboard about 60 more cameras** toward a 100-camera fleet, gated by tier, with the same frozen setting. Prefer diversity: states, river sizes, flash-flood creeks, coastal/tidal (exercises W2-1), cold climate.
   - Report the scale numbers: cameras onboarded per CPU-hour, $ per camera, % qualifying by camera type.
   - Hand bundles to W1. The m9g cycle must stay < 15 min with v1+v2 (W1 measures). If it doesn't, onboarded sites run every 30 min.
2. **"Add a camera" request flow (UI + queue, human-approved):** a user picks any gauged HIVIS camera from a list → a request lands in `live/onboard_requests/` → an operator approves → the pipeline runs. A demo of self-service scale. No automatic heavy compute without approval.

## W3 — evidence, docs, assets
1. Fix the botocore test (approved earlier), then re-time the fresh clone.
2. **Video B-roll:** scripted Playwright captures of the live site at 1080p (MP4 or WebM, plus GIFs):
   - home → Salt Creek slider sweep
   - flood replay (once W1-2 lands)
   - `/judge`
   - `/approvals` with the First Mallard approval
   - `/proof`
   - `/health`

   Put them in `results/video_assets/` (gitignored if large; list them in a manifest). Samuel narrates over them Sunday. **Highest-leverage W3 item.**
3. **Devpost text draft** in `docs/DEVPOST.md`: every field (tagline, story sections, built-with, links), every number traced. Cowork edits it Saturday night.
4. Report final: fused-estimate results, tidal fix, health QA eval, scale numbers, the documented First Mallard false alert. The final PDF lands Sun 18:00 CT, and an updated one Mon 12:00.
5. **`docs/ROADMAP.md`:** the post-competition ship plan (all ~1,300 cameras, public API, partnerships, night models, ungauged transfer). Judges score real-world impact; show the path.

## Rules (unchanged)
- Frozen results are never recomputed.
- Every new claim comes from a committed results file, produced by a committed script.
- Post-freeze changes go in a `POST_FREEZE_CHANGES` log.
- Bedrock spend stays ≤ $25.
- AWS projection stays ≤ $100 (W1 reports it).
- Owners touch only their own paths. Cross-path edits need a Cowork note in HUMAN.md.
