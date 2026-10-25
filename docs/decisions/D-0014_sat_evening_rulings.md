# D-0014 — 2026-10-24 (Sat 19:45 CT) — Gate G2 audit; v2 serves now; Q-0013; king tides; Bedrock line; Sunday work (Cowork)

## Gate G2 audit (live site, desktop, night Central time)
**Strong:**
- the fused "RiverSight stage" headline with a provenance pill and a plain-language "why"
- night fallback
- the "Needs a person now" triage panel
- **"Replay a flood" at Salt Creek works well:** the wet overlay climbs the bank, the camera-vs-gauge chart with cursor, the agent's DENSIFY → DRAFT_ALERT log in time, and "above range — gauge trusted" during the crest. This is the demo centrepiece.
- `/health`, the Data API, `/approvals` with the second opinion
- the Devpost draft (`docs/DEVPOST.md`) is good; Cowork edits are below

**Fix (W1 unless noted):**
1. **Headline count mismatch.** The home title says "Live: 20 USGS river cameras" but the strip says 50. New title: "Live: 50 USGS river cameras read as water-level gauges", with the subline "20 frozen-test cameras + 30 onboarded this weekend". Same on `/judge` step 1.
2. **Stale approvals clutter the triage panel.** Animas shows "OPEN_TICKET ×14" and First Mallard shows old tide alerts.
   - Add an **approval TTL**: a pending item older than 24 h becomes `expired` with a reason, is kept in the log and leaves the panel.
   - Confirm W2's ticket/alert hysteresis is deployed. The counts should not grow per cycle.
   - The triage list shows only live, unexpired items.
3. **Approval cards for tidal alerts** created before the fix: mark them "superseded by tidal logic (D-0013 W2-1)". Samuel will still reject them by hand, as the honest record.

## v2 serving decision (D-0010 §2): **v2 serves now**
- **Criterion 1:** CV 0.252 vs 0.380 ft, 19/20 sites better, no site worse by > 0.10. Met.
- **Criterion 2:** live shadow median AE 0.084 vs 0.183 ft on **249 paired readings**, 16 sites; site-bootstrap CI of the difference −0.236 to −0.021. Met. Caveat: one calm day.
- **Criterion 3:** cycle < 5 min on the worker. Met (W1).
- **W1:** serve v2 from tonight's deploy.
  - **v1 stays as the shadow, and the frozen-v1 prospective record continues as pre-registered.**
  - The site page shows "model v2 (DINOv2 in cv2.dnn), promoted Oct 24 by D-0014 under pre-registered criteria".
  - The prospective scorer reports three groups: frozen v1, served v2 since promotion, onboarded.

## Q-0013 → (a) + (b)
- Keep the $100 budget. Move the stop action to **100%** (`infra/stacks/guard.py`); alerts stay at 25/50/75/90%.
- Every further AWS action expected to cost > $2 goes through Cowork.
- W1 posts actual and projected spend daily on `/proof` and in its status.

## Bedrock line → raised to **$35 total** (inside the $100 AWS cap)
- Live Sonnet 4.6 second opinions and drift reviews only, with `RIVERSIGHT_AGENT_DAILY_TOKENS=150000` (about $0.5/day). Past the cap the rules keep deciding.
- No more evaluation runs unless Cowork approves.

## King tides → yes, as a low-severity advisory
- When the *predicted* tide itself exceeds the site's daily-max p99, draft a `TIDE_ADVISORY` ("predicted high tide above this site's typical maximum; NWS may issue a coastal flood advisory").
- Severity low; it needs approval like any alert.
- It's a post-freeze change, logged in `POST_FREEZE_CHANGES.md`. Add it to the episode set as v5 with expected actions written first, and rerun **rules and hybrid only**, at Bedrock cost < $2.

## Sunday work (each owner continues down this list; freeze Mon 12:00 CT)
**W1**
1. G2 fixes 1–3.
2. v2 serving.
3. The guard at 100%.
4. Onboard W5's batch-2 tier-B bundles as they land (W5 hands them off). Keep the cycle under 15 min; onboarded sites move to 30 min if needed.
5. Uptime and latency watch. No risky changes after Mon 12:00.

**W2**
1. King-tide advisory (above).
2. **Recalibration as an agent action:** when a site's camera-vs-gauge residuals drift (W4's signal), the agent drafts `RECALIBRATE` with evidence. A human approves. The worker then promotes the shadow-refit bundle (W4-1 below). Rules policy only; no new Bedrock spend.

**W4**
1. **Weekly self-recalibration on the worker, shadow-first.**
   - The cycle already computes features per reading. Persist them with the matched gauge to S3, then run a weekly ridge refit (v2 config) on the worker to produce `models/sites_recal/<cam>`.
   - Score it as a shadow in the prospective scorer.
   - Promotion only via W2's `RECALIBRATE` approval.
   - **Must be finished and tested by Mon 10:00 CT, or it ships disabled and goes in the roadmap.** CV evidence: weekly refit 0.240 vs fit-once 0.361 ft (v1), 0.165 with v2; out-of-range share 7.9% → 1.7%.
2. Night/IR flood state stays out of scope (documented reason). It's in the roadmap.

**W5**
1. Batch 2: hand tier-B bundles to W1.
2. Update the scale numbers.
3. Process the first "Add a camera" request after approval. Samuel or Cowork approves it on `/approvals`.

**W3**
1. **Video rough cut.** Assemble the B-roll into a silent `results/video_assets/rough_cut.mp4` that follows `docs/VIDEO_SCRIPT_DRAFT.md` v3 shot by shot:
   - title cards with `cv2.FontFace` text
   - the replay segment captured from Salt Creek
   - an end card with the URL and repo
   - target 3:15, with intro and outro slots left for Samuel on camera

   Samuel records voice and face, and only has to drop them in.
2. Recapture B-roll after W1's G2 fixes: home with the 50-camera title, the replay, approvals.
3. Report final by Sun 18:00 with: v2 promotion; frozen-v1 prospective vs served v2; the tidal fix + king-tide advisory; the recalibration status; scale batch 2.
4. Make the DEVPOST.md edits below, then generate the final paste-ready text.

### DEVPOST.md edits (W3)
- **What it does:** add a bullet "**Replay a flood:** every featured site can replay a real past flood frame by frame (camera, gauge, overlay, agent decisions), so you can see it work even when rivers are calm."
- **Accomplishments:** after v2's shadow result, add "promoted to the live model on Oct 24 under pre-registered criteria".
- **Links:** "Start at /judge, then Salt Creek → Replay a flood".
- Keep everything else. It is honest and specific.
