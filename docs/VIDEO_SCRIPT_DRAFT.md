# RiverSight video — draft script v2 (Cowork, Oct 23; W3 fixes applied; final after Gate G2, Sat evening)

**Target length:** 3:15 (limit 5:00). The demo comes first. Samuel appears on camera at 0:00–0:12 and 2:55–3:15; screen capture with his voice-over in between.

Numbers in `{braces}` are filled only from committed files. The ones already safe come from W3's list in `docs/status/W3_brief_for_cowork.md`. Never say "first camera water-level system", "first on HIVIS", "replaces gauges", or that we beat StageSight. Never quote a COOL speedup that wasn't measured on AWS.

| time | picture | words (Samuel) |
|---|---|---|
| 0:00–0:12 | Samuel on camera, then a cut to the live site home | "I'm Samuel. About 880 public USGS river webcams sit right next to stream gauges. RiverSight turns them into a second, independent water-level instrument. Twenty are live today." |
| 0:12–0:40 | Pecatonica site page: the latest daylight frame with the blue overlay; drag the slider from 5 to 9 ft and the water climbs the bank | "This is the USGS camera on the Pecatonica River in Wisconsin. The camera reads {x.x} feet; the gauge says {y.y}. Drag the slider and you see what goes under water at any level. Each patch of the picture learned the level at which it gets wet from a year of the gauge's own history: no survey, no staff plate, no targets." |
| 0:40–1:05 | Pipeline: frame → ALIKED+LightGlue inlier lines → reliable blocks highlighted → stage ± σ | "Every frame is registered with OpenCV 5's ALIKED and LightGlue with MAGSAC. Plain ORB registers only 40% of daylight frames; this gets 95.7%. A regression over the reliable patches turns the picture into feet, with an error bar." |
| 1:05–1:35 | `/judge` tiles: 14/20, 0.18 ft, 15/20 and 18/20, 0/20 | "We froze the model, then scored 20 cameras once on ten unseen days: 14 of 20 within a quarter foot or 10% of their range, median error 0.18 feet. When a gauge goes dark, the camera beats its 72-hour-old reading at 15 of 20 sites and its week-old reading at 18. While the gauge is online the gauge wins, and we show that too." |
| 1:35–2:15 | River Steward: Hancock flood replay timeline → wet overlay → drafted alert → the approvals page → Samuel taps Approve → email arrives | "A fleet agent, River Steward, watches every camera. When OpenCV loses registration it re-checks against a reference bank and re-anchors or quarantines. When water rises it samples faster, draws the forecast crest into the image and drafts an alert. Nothing goes out without a human. On {N} episodes, {48} of them real, it took the right action {a}% of the time, against {92.3}% for fixed rules, with zero false actions on clean controls." |
| 2:15–2:40 | Architecture diagram → `/proof` → COOL per-kernel chart | "It runs on AWS Graviton with OpenCV's COOL build. Per kernel, {k}; end to end, {e}× with identical outputs, which works out to {$} per camera-month to watch the whole fleet. Fresh clone to all-green tests takes about 70 seconds." |
| 2:40–2:55 | Failure gallery: night, hazy lens, re-aimed camera, the Hancock flood above range | "It doesn't see at night. Fog and muddy water look alike to it. Eight of twenty cameras had stretches it couldn't register to today's view. And a flood bigger than anything in the camera's history pins it at its ceiling. Then it says 'at least this high' and trusts the gauge." |
| 2:55–3:15 | Samuel on camera | "Gauges go dark, drift and get damaged. Cameras are already there. RiverSight makes them a check, a backup, and a picture of where the water is." |

**Recording checklist:**
- 1080p screen capture; mic test.
- Dashboard in light mode; record in daylight Central time so the frames are live, or use the "last daylight frame" view.
- Replays labelled "replay".
- End card with the URL, repo and team (Samuel).
- Keep it under 3:30.
