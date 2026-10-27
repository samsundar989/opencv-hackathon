# RiverSight video: final recording package (Cowork, updated Tue Oct 27 00:15 CT: v2 now live, /judge clicks for shots 4–6, COOL box)

**Target:** 3:00–3:30 (limit 5:00). **Must show:** the team (you on camera), the app working, the architecture, the principal results.
Every number below is one already in `docs/VIDEO_SCRIPT_DRAFT.md` v3.1 or `docs/DEVPOST.md`. Add no new numbers.

## It's night in the US: read this first
Live cameras show night/IR right now, so site pages show the gauge with a night pill. Demo with **Replay a flood** (precomputed, works any time) and the **stage slider**, which draws on the last daylight frame. Don't wait for a live daylight reading.

## Shot list (base URL `https://d2aes2r6og8aap.cloudfront.net`)
| # | time | on screen (exact clicks) | narration |
|---|---|---|---|
| 1 | 0:00–0:15 | **Webcam**, you at eye level → cut to the home page `/` | "I'm Samuel, and this is RiverSight. River gauges go dark, drift and get washed out, often during floods. In the past year, 531 of the 875 gauges behind USGS's public river cameras had an outage of six hours or more. The cameras next to them are never read as instruments. RiverSight reads them." |
| 2 | 0:15–0:40 | `/` → click the **Salt Creek** card → drag the **stage slider** slowly from low to high | "This is the USGS camera on Salt Creek, Illinois. Drag the slider and the picture shows what is under water at that river level. Each patch of the image learned the level at which it gets wet from the gauge's own history. No survey, no staff plate. Water is only drawn where it connects to the river." |
| 3 | 0:40–1:15 | Same page → scroll to **Replay a flood** → click **▶ Play**; let the overlay rise; point the cursor at the chart, then the agent log | "Here is a real flood from July, replayed out of sample: the model never saw it. As the creek rises, the agent samples faster and drafts an alert, which waits for a person. At the crest the water goes above anything this camera was trained on, so it says 'at least this high' and trusts the gauge." |
| 4 | 1:15–1:35 | `/judge` → scroll to the **"Frozen test (protocol v2, scored once)"** grid of big numbers; point at **PASS**, **0.18 ft**, **14/20**, **95.7%** as you say them | "How well does it work? OpenCV 5's ALIKED and LightGlue with MAGSAC line up 95.7% of daylight frames to a reference view; ORB manages 39.6%. We froze the model and scored 20 cameras once on unseen days. 14 of 20 were within a quarter foot or 10% of range. The median error was 0.18 feet." |
| 5 | 1:35–1:55 | Same grid: point at **15/20** and **18/20** (gauge-outage gap-fill), **0.93 vs 0.75** (flood state), then **0/20** on "not a working gauge". Optional: the Salt Creek row in the per-site table (0.09 ft; 72 h outage 0.09 vs 1.03 ft) | "Does it beat the gauge? Not a working gauge, and we say so. It beats a dead one. When the gauge goes dark, the camera beats its 72-hour-old reading at 15 of 20 sites, and its week-old reading at 18. It calls flood state correctly at 0.93 balanced accuracy, versus 0.75 for a day-old gauge." |
| 6 | 1:55–2:10 | No v2 tile exists: stay on `/judge` (or show README "Model v2" bullet on GitHub). Optional shot; cut if long | "A DINOv2 model running inside OpenCV's DNN engine cut year-long error from 0.38 to 0.25 feet. In a pre-registered live side-by-side test it beat the current model, 0.08 to 0.18 feet. So it's now the live model." |
| 7 | 2:10–2:40 | `/approvals` → open one card (show the Claude second opinion) → `/health` | "River Steward is the agent. We measured who should act. On 98 frozen test cases, OpenCV-grounded rules scored 94% and Claude alone 71%. So the rules act, Claude on Amazon Bedrock ranks the fleet and gives a second opinion, and a person approves anything that leaves the system. It also watches the cameras themselves: offline, moved, or stuck in infrared." |
| 8 | 2:40–3:05 | Open `docs/img/architecture.svg` in the browser (from the repo, or GitHub) → `/judge` → scroll to the **"COOL on Graviton"** box (instance, COOL build, baseline, 1.0067× flat, 1.16–1.21× registration, why flat, $0.059/camera-month) → `/proof` | "It runs every 15 minutes on AWS Graviton5 with OpenCV's COOL build: EC2, S3, CloudFront, Lambda, Bedrock, CloudWatch, all in CDK. COOL gives the same outputs and speeds up registration by 16 to 21%. End to end it's flat, because the neural matcher dominates, and we show that. One server covers all 880 gauged cameras for about six cents per camera-month. 64 of 90 new cameras onboarded themselves at about six cents of compute each." |
| 9 | 3:05–3:15 | Failure gallery (in `/judge` or the report) | "It can't see at night. Fog fools it, cameras get re-aimed, and the biggest floods saturate it. All of that is flagged, not hidden." |
| 10 | 3:15–3:30 | **Webcam** → end card (live URL + repo) | "Gauges go dark, drift and get damaged. The cameras are already there. RiverSight makes them a backup, a check, and a picture of where the water is." |

**Award evidence these shots cover:**
- *COOL:* shot 8 shows the AMI/instance on `/proof`, the fair A/B and the Amdahl chart.
- *Agentic Vision:* shot 3 shows OpenCV output (rising stage, out of range) changing the agent's actions; shot 7 shows the rules and human approval.
- *Main rubric:* shots 4–6 cover evaluation, shot 9 failure cases, shot 8 architecture and cloud.

## Optional whiteboard (20 s, instead of the SVG in shot 8)
Draw: camera → OpenCV 5 registration → flood-height map → stage ± σ → rules agent (+ Claude advisor) → human approval → alert.
**Recommendation: skip it.** The SVG is faster and cleaner. Use the whiteboard only if you want more face time and have 10 spare minutes.

## Trupeer (or similar AI editor) recipe, about 45–60 min
1. **Webcam clips:** record the intro (shot 1, about 15 s) and the outro (shot 10, about 15 s). Two takes each; keep the best.
2. **Screen take:** set the browser window to 1920×1080. Start a screen recording in Trupeer (or OBS/Clipchamp, then import). Do shots 2–9 in **one take**, following the clicks above at a calm pace. Pause about 2 s on each tile.
3. **Voice:** either read the narration live while recording (most authentic), or record silently and paste the narration block below into Trupeer's script/voiceover box. If Trupeer offers an AI voice or a "clean up my voice" option, use it, and keep your own voice if it's clear.
4. **Polish:** if Trupeer offers auto-zoom on clicks, turn it on; it's important for the slider and the replay. Turn captions on.
5. **Assemble:** intro clip → screen take → outro clip. Add an end card with `d2aes2r6og8aap.cloudfront.net` and the repo URL. Trim to 3:30 or less.
6. **Export** at 1080p MP4. Upload to YouTube as **Unlisted** (or Public). Paste the link into Devpost → Project details → Video → Save & continue. Confirm it plays logged out.
7. **Fallback:** if you're short on time at 01:20 CT, upload `results/video_assets/rough_cut.mp4` and keep that link.

## Narration only (paste into an AI voiceover tool)
I'm Samuel, and this is RiverSight. River gauges go dark, drift and get washed out, often during floods. In the past year, 531 of the 875 gauges behind USGS's public river cameras had an outage of six hours or more. The cameras next to them are never read as instruments. RiverSight reads them.

This is the USGS camera on Salt Creek, Illinois. Drag the slider and the picture shows what is under water at that river level. Each patch of the image learned the level at which it gets wet from the gauge's own history. No survey, no staff plate. Water is only drawn where it connects to the river.

Here is a real flood from July, replayed out of sample: the model never saw it. As the creek rises, the agent samples faster and drafts an alert, which waits for a person. At the crest the water goes above anything this camera was trained on, so it says "at least this high" and trusts the gauge.

How well does it work? OpenCV 5's ALIKED and LightGlue with MAGSAC line up 95.7 percent of daylight frames to a reference view; ORB manages 39.6 percent. We froze the model and scored 20 cameras once on unseen days. 14 of 20 were within a quarter foot or 10 percent of range. The median error was 0.18 feet.

Does it beat the gauge? Not a working gauge, and we say so. It beats a dead one. When the gauge goes dark, the camera beats its 72-hour-old reading at 15 of 20 sites, and its week-old reading at 18. It calls flood state correctly at 0.93 balanced accuracy, versus 0.75 for a day-old gauge.

A DINOv2 model running inside OpenCV's DNN engine cut year-long error from 0.38 to 0.25 feet. In a pre-registered live side-by-side test it beat the current model, 0.08 to 0.18 feet. So it's now the live model.

River Steward is the agent. We measured who should act. On 98 frozen test cases, OpenCV-grounded rules scored 94 percent and Claude alone 71 percent. So the rules act, Claude on Amazon Bedrock ranks the fleet and gives a second opinion, and a person approves anything that leaves the system. It also watches the cameras themselves: offline, moved, or stuck in infrared.

It runs every 15 minutes on AWS Graviton5 with OpenCV's COOL build: EC2, S3, CloudFront, Lambda, Bedrock, CloudWatch, all in CDK. COOL gives the same outputs and speeds up registration by 16 to 21 percent. End to end it's flat, because the neural matcher dominates, and we show that. One server covers all 880 gauged cameras for about six cents per camera-month. 64 of 90 new cameras onboarded themselves at about six cents of compute each.

It can't see at night. Fog fools it, cameras get re-aimed, and the biggest floods saturate it. All of that is flagged, not hidden.

Gauges go dark, drift and get damaged. The cameras are already there. RiverSight makes them a backup, a check, and a picture of where the water is.

## Pre-recording checklist
1. Browser window at 1920×1080, zoom 100%, light mode, bookmarks bar hidden.
2. Close other tabs. Turn notifications off (Windows Focus Assist on).
3. **Hard-refresh** each page (Ctrl+Shift+R) so you get the newest UI deploy.
4. Test run: Salt Creek → Replay a flood → ▶ plays to the end, the overlay rises and the agent log fills in.
5. Have `architecture.svg` open in a tab, ready for shot 8 (the COOL box is on `/judge`).
6. Microphone check (10 s test). A quiet room; the webcam at eye level and lit from the front.
