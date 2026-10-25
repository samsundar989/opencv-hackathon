# RiverSight video — script v3 (FINAL for recording Sun ~10:00 CT) — Cowork, Oct 24 evening

**Length:** 3:15–3:30 (limit 5:00).
- Samuel appears on camera at the start and the end; everything else is his voice over W3's B-roll (`results/video_assets/`, rough cut `rough_cut.mp4`).
- Every number below is in `docs/DEVPOST.md` and traced by `scripts/check_report_numbers.py`. If W3's final report changes any of them, use the report's value.

| # | time | picture (B-roll file) | words (Samuel) |
|---|---|---|---|
| 1 | 0:00–0:15 | Samuel on camera → cut to the live home page (`home.mp4`) | "I'm Samuel. Stream gauges go dark, drift and get washed out, and in the past year 531 of the 875 gauges behind USGS's public river cameras had an outage of six hours or more. The cameras next to them are never read as instruments. RiverSight reads them." |
| 2 | 0:15–0:45 | Salt Creek site page, slider sweep (`salt_slider.mp4`) | "This is the live USGS camera on Salt Creek, Illinois. Drag the slider and the picture shows what goes under water at any stage. Each patch of the image learned the level at which it gets wet from the camera's own gauge history: no survey, no staff plate. Water is only drawn where it can connect to the river." |
| 3 | 0:45–1:20 | **Replay a flood** at Salt Creek (`replay.mp4`): overlay rising, chart cursor, agent log | "Here is a real flood from July, replayed out of sample. As the creek rises, the agent samples faster, drafts an alert with these overlays, and waits for a person. At the crest the water goes above anything the camera was trained on, so it says 'at least this high' and trusts the gauge." |
| 4 | 1:20–1:45 | Registration graphic → `/judge` tiles (`judge.mp4`) | "Under the hood, OpenCV 5's ALIKED and LightGlue with MAGSAC register 95.7% of daylight frames, against 39.6% for ORB. We froze the model and scored 20 cameras once on unseen days: 14 of 20 within a quarter foot or 10% of range, median error 0.18 feet. When the gauge goes dark, the camera beats its 72-hour-old reading at 15 of 20 sites and its week-old reading at 18." |
| 5 | 1:45–2:10 | v2 / prospective tiles on `/judge` | "A DINOv2 model running inside OpenCV's DNN engine cut year-long error from 0.38 to 0.25 feet. It went live today after beating the old model in a pre-registered live shadow test. And while the gauge is online, the gauge still wins; we show that too." |
| 6 | 2:10–2:40 | `/approvals` (second opinion on the card), "Needs a person now", `/health` (`approvals.mp4`, `health.mp4`) | "River Steward is the fleet agent. We measured who should act: on 98 frozen test cases, OpenCV-grounded rules scored 94%, Claude alone 71%. So the rules act, Claude on Bedrock ranks the fleet and gives a second opinion, and a person approves anything that leaves the system. It also watches the cameras themselves: offline, moved, or stuck in infrared." |
| 7 | 2:40–3:00 | Architecture diagram → `/proof` (`proof.mp4`) | "It runs every 15 minutes on AWS Graviton5 with OpenCV's COOL build. COOL gives identical outputs and speeds up registration by 16 to 21%, but it's flat end to end because the neural matcher dominates. One server covers every gauged HIVIS camera for about six cents per camera-month. Thirty of forty new cameras onboarded themselves this weekend." |
| 8 | 3:00–3:10 | Failure gallery montage | "It can't see at night, fog fools it, cameras get re-aimed, and floods beyond its history saturate it. All of that is flagged, not hidden." |
| 9 | 3:10–3:25 | Samuel on camera → end card (URL, repo) | "Gauges go dark, drift and get damaged. The cameras are already there. RiverSight makes them a check, a backup, and a picture of where the water is." |

## Recording plan (Sun ~10:00 CT)
1. **Before:** run `aws login`; open the live site in **daylight** (Salt Creek or Neversink should show "camera" readings), light mode, and close other tabs.
2. **On-camera parts (shots 1 and 9):** phone or webcam, eye level, quiet room, 2–3 takes each.
3. **Voice-over (shots 2–8):** read over W3's `rough_cut.mp4`, or re-record the screen live with OBS or Clipchamp while narrating. A live take of the slider and replay looks more authentic.
4. **Edit:** drop the on-camera clips into the rough cut's intro/outro slots and add the narration. Keep it under 3:30. Export 1080p MP4.
5. **Upload:** YouTube (unlisted or public) or Vimeo. Paste the link in Devpost.
