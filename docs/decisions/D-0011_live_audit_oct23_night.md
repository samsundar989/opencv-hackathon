# D-0011 — 2026-10-23 (Fri 20:30 CT) — Cowork judge-eye audit of the live site; new must-fix items

**Live URL:** https://d2aes2r6og8aap.cloudfront.net. Audited in Chrome at night Central time on the home page, the site pages (Neversink, Salt Creek), and `/judge`.

## Verdict
Gate G1 is met. The site runs on the COOL G5 AMI (m9g.large; `proof.json` reports `cv2 5.1.0-dev` from `/opt/cool`). The budget guard is live, and all of D-0009 W1-1 to W1-7 is in.

What works well:
- night fallback to the last daylight frame
- out-of-range handling
- vendored libraries
- dark mode
- `/judge` copy
- Salt Creek: the slider fills the channel to the wall at high stage, which is convincing

**Since about 16:35 CT, no worker has committed anything.** The round-2 prompts (W4, W5, add-ons) have not been started. That time is lost; resume immediately.

## New must-fix items (W1 unless noted), in priority order

1. **Physically consistent wet overlay (credibility; also an innovation point).**
   - **The problem today:** at Neversink, sliding the stage up paints blue blocks on the forested hillside and the sky. A judge will see that as nonsense.
   - **Fix: connected inundation.**
     1. Seed with the "always wet" blocks: h* ≤ calibration p05, or the largest connected component of low-h* blocks in the lower half of the frame.
     2. At stage s, flood-fill from the seed through 4-connected blocks with h* ≤ s and reliability ≥ threshold, using `cv2.floodFill` or `connectedComponentsWithStats` on the block grid.
     3. Blocks not connected to the seed are never drawn.
   - Apply it in the client slider (JS over `hstar.json`) and in the server overlay (OpenCV).
   - Add a "connected-inundation" sentence to the report (W3) and to `OPENCV5_USAGE`.
   - Keep the frozen evaluation untouched; this is display only. W2's `render_wet_overlay` uses the same function.
2. **The agent-evaluation panel on `/judge` renders raw JSON.** Render a table instead:
   - per arm: task success, real vs synthetic, false actions, triage, $
   - the success-by-kind matrix
   - the flood replays with links to the figures
   - the honest limits as bullets
3. **Night cards need the camera's last reading.** Show the last daylight camera estimate next to the gauge at that time, e.g. "camera 3.58 ft at 4:00 PM, gauge then 3.60 ft". The camera-vs-gauge comparison should be visible at any hour, because judges will look at night.
4. **The home strip at night reads as broken** ("1 OK, 1 flagged"). Count every status: "17 at night (gauge only) · 1 OK · 1 flagged · 1 stale camera".
5. **Featured order.** Pecatonica's camera has uploaded nothing since Oct 20, so stop leading with it. New order: Salt Creek, Neversink, Hancock, Bean Creek, Stony Brook, Buffalo Bayou, then Pecatonica (still showcased through its flood-height map on `/judge`).
6. **Site-page load time.** The frame area stays blank for several seconds. Fix:
   - show the card thumbnail immediately, then swap in the full frame
   - serve frames as WebP or quality-80 JPEG at ≤ 1280 px
   - `Cache-Control: max-age` on immutable frame keys
   - target: first paint of the image under 1 s on broadband
7. **Prospective scoring (D-0010 §1).** This is still missing. Set it up now with this window:
   - **Start:** the first COOL cycle (Oct 23 ~16:28 CT).
   - **Frozen models:** the bundles carrying the `model_sha` values served in that cycle. Record them in `results/live_prospective/frozen_models.json`.
   - This is still pre-registered: D-0010 was written to the repo at about 16:15 CT, before that cycle.
   - Readings from before the COOL cycle are excluded.

## Samuel
- Click **Confirm subscription** in the two AWS SNS emails (`riversight-stop`, `riversight-alerts`). Without the stop confirmation, the $90 stop action can't email you.
- Accept the Claude Haiku 5.5 and Sonnet 5.5 agreements in the Bedrock console (Q-0010).
- Paste the round-2 prompts (`NEXT_PROMPTS_2026-10-23b.md`): **W5** and **W4** as new sessions, and the add-ons into W1, W2 and W3. Then paste this D-0011 into W1.
