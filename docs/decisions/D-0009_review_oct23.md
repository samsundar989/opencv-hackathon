# D-0009 — 2026-10-23 (Fri ~16:00 CT) — Cowork review of W1/W2/W3; answers to the W2 and W3 briefs; must-fix list before Gate G2

## Review verdict
The work is strong. Everything that can be done offline is done, every number traces to a committed file, and the integrity trail (re-freezes before LLM arms, superseded runs kept) is exactly what the judges reward.
- **The only blocker is AWS login** (Q-0008). Samuel is unblocking it now.
- **Cowork checked the dashboard** by rendering `web/` + `live_local/` with Playwright at 1280 px and 390 px.
  - `/judge` is excellent.
  - The site page has four demo-breaking problems, listed below as W1-1 to W1-4.

## Answers to W3's brief
1. **Hancock head-to-head:** keep §6.6 in the main report, as written. Matching StageSight's rigor was the point, and a disclosed loss reads as integrity.
   - Add one forward-looking sentence: *each flood the gauge records extends the camera's calibrated range, because the bundle is refit on new data.* Only add it if W1's recalibration job actually exists; otherwise leave it as future work.
2. **Out-of-range safety flag:** accepted. See W1-1 and W2-1.
3. **Video-script fixes:** all accepted. Cowork has updated `docs/VIDEO_SCRIPT_DRAFT.md`.
4. **Corrected numbers:** use "8 of 20 cameras have periods that can't be registered to the current view" and "9/19 on the fit window" everywhere: README, report, `/judge`, video.
5. **Secrets scan:** rerun Monday before Samuel decides whether the repo goes public.

## Answers to W2's brief
- **D1 Bedrock budget.** Proceed in this order, stopping if the pilot's measured cost says otherwise:
  1. 5-episode pilot
  2. Haiku 3× on the full set
  3. Haiku-without-OpenCV 3×
  4. Sonnet **1×** on the full set
  5. Sonnet 2× more, only if the measured cost for this step is ≤ $10 (D-0008)

  Log the real $ in `docs/status/W2.md`. Claude-on-Bedrock may not be covered by AWS credits, so this may hit Samuel's card; it stays inside the $100 cap.
- **D2 no gauge-drift rule:** agreed. Keep the honest 0/3 as the place where the LLM can show what it adds. If Haiku also misses, report it.
- **D3 video assets:** use the Hancock timeline and the Salt Creek alert now. Swap in the LLM versions when they exist.

## Must-fix before Gate G2 (Sat 18:00 CT), in priority order

### W1 (dashboard and live cycle)
1. **Out-of-range readings.**
   - **The problem today:** Animas shows `camera 4.24 ± 0.63 | gauge 8.32 | flood | status OK`. A judge will read that as the system being confidently wrong.
   - **Fix:**
     - Add an `OUT_OF_RANGE` flag when the raw camera estimate is within σ of the bundle's `stage_max` or the gauge is above `stage_max`.
     - Display "≥ 4.6 ft (above calibrated range)", not a number with ±σ.
     - The status pill must not say OK. Use "above range — gauge trusted".
     - Fire `DISAGREE` immediately, without waiting 3 cycles, when the gauge is outside the calibrated range.
2. **Night and stale fallback.**
   - **The problem today:** a site with no new daylight frame shows an empty slider and "No live reading yet". Pecatonica, our best site, looked like that during Cowork's render.
   - **Why it's critical:** judges will look at some point in a 24 h day, and at night every site goes blank.
   - **Fix:** always show the **last good daylight frame** with its overlay, slider and timestamp ("last daylight frame 14:00 CDT"), plus a night or stale banner. The gauge-only reading carries on at night.
3. **No CDN dependency.**
   - **The problem today:** if cdnjs fails, `new Chart` throws and the rest of the site page never renders. Cowork's render showed "Frozen-test result: —" for that reason.
   - **Fix:** vendor Leaflet and Chart.js into `web/assets/vendor/`, MIT-licensed, with the licence files. Wrap each panel's render in its own try/catch so one failure can't blank the others.
4. **Featured sites.**
   - **Fix:** order the home grid and the `/judge` tour by demo quality: Pecatonica, Salt Creek, Hancock, Neversink, Bean Creek, Stony Brook, Buffalo Bayou.
   - **Why:** at Animas the overlay paints blocks on the water surface, which is a weak first impression. Pecatonica's bank gradient is the money shot.
5. **Privacy mask.**
   - **The problem today:** a solid black rectangle sits on the Animas frame (top centre). It looks like a YuNet false positive filled with black.
   - **Fix:** use a strong Gaussian blur or pixelation instead of a black fill, raise YuNet's score threshold a little, and log the detections.
6. **Quarantine release** (W2's note): lift the quarantine after N = 3 consecutive cycles with registration OK and |cam − gauge| ≤ 2σ, or on `SET_REFERENCE`. Log it.
7. **Copy fixes on `/judge`:**
   - "7 of 20 cameras were re-aimed or moved" → "8 of 20 cameras have periods that can't be registered to the current view."
   - Make the cadence match what's deployed: the page says 30 min, the infra timer says 15. Pick one and use it everywhere. **15 min** is fine if the cost holds.

### W2 (agent)
1. **Out-of-range behavior.** An `OUT_OF_RANGE` reading never produces a camera-only number:
   - With the gauge available → trust the gauge, flag the camera as saturated (not "faulty"), and keep the camera's flood-state vote.
   - With the gauge stale → `MARK_PROVISIONAL` with "≥ X ft".
   - Add episodes (Hancock Jul 29, Animas now) and re-freeze **before** the LLM arms run.
2. **LOW_QUALITY during a rise:** don't discard a frame on quality alone while `RISING` (muddy water is not fog).
3. **After login:** pilot → arms per D1 → approval round-trip on the live stack with a screenshot → kill-switch and token-cap demo.

### W3 (report, COOL, docs)
1. Report v2 on Sat with the corrected numbers.
2. COOL A/B as soon as the bucket and AMI exist. If the AMI isn't subscribed by **Sat 12:00 CT**, run the pip-vs-pip arm on Graviton (m9g, stock) as a Graviton-vs-x86 baseline and say plainly that COOL wasn't run.
3. Make sure `check_report_numbers.py` covers the `/judge` copy.
