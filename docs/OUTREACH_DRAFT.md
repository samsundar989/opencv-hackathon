# Outreach draft: USGS HIVIS team (Samuel sends from his own email once the live URL works)

**To:** hivis@usgs.gov (listed on https://api.waterdata.usgs.gov/docs/nims/hivis as the contact for HIVIS questions and comments)
**Subject:** Using HIVIS cameras as a backup water-level reading: open project, feedback welcome

Hello HIVIS team,

I'm a software engineer who has been building an open-source project on top of the public HIVIS camera feed and the NIMS API. It reads river stage from the camera images and checks it against the co-located USGS gauge.

How it works, in short:
- Each camera calibrates itself from its own gauge history. There's no survey, staff plate or target.
- On 20 cameras, scored once on ten held-out days, the camera estimate was within 0.25 ft (or 10% of range) at 14 of 20 sites.
- When a gauge reading is stale, the camera beats a 72-hour-old reading at 15 of 20 sites.
- It is not a replacement for a working gauge. While the gauge reports, the gauge is better.
- An agent flags cameras that have moved, lost focus or disagree with their gauge. Any alert waits for a human to approve it.

The live site is at {URL}, and the code and full evaluation are at {REPO}. It was built for the OpenCV AI Competition 2026. I'd like to keep developing it beyond that, and I'd value your view on whether a gap-fill or camera-QA signal like this would be useful to you or your cooperators. I'd also like to know if there are cameras or uses we should avoid.

Thank you for making the imagery public.

Samuel {surname}
{email / GitHub}
