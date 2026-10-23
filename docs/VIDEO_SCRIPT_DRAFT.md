# RiverSight video — draft script (Cowork, Oct 22; final version after Gate G2, Sat evening)

**Target length:** 3:15 (limit 5:00). The demo comes first. Samuel appears on camera at 0:00–0:12 and 2:55–3:15; screen capture with his voice-over in between. Numbers in `{braces}` get filled from committed results files only.

| time | picture | words (Samuel) |
|---|---|---|
| 0:00–0:12 | Samuel on camera, then a cut to the live site | "I'm Samuel. America has about 900 public river webcams sitting next to USGS stream gauges. RiverSight turns every one of them into a second, independent water-level instrument, live, right now." |
| 0:12–0:40 | Live dashboard: map → a site page. The latest frame with the blue wet-area overlay; drag the stage slider up and the water climbs the bank. | "This is the actual USGS camera on the Pecatonica River, minutes old. The camera reads {x.x} ft ± {σ}, and the gauge says {y.y}. Drag the slider and you see what goes under water at any stage. We learned that from a year of the gauge's own history, with no survey, no staff plate and no targets." |
| 0:40–1:10 | Pipeline animation: frame → ALIKED+LightGlue registration (inlier lines) → block features → flood-height map → stage ± σ | "Each frame is registered with OpenCV 5's ALIKED and LightGlue with MAGSAC. Then each patch of the image has learned the water level at which it gets wet, a flood-height map. Those pixels vote, and a regressor turns them into feet." |
| 1:10–1:40 | Kill-test table and gap-fill chart | "We froze the model, then scored 20 cameras once on ten unseen days. {14} of {20} were within a quarter foot or 10% of range. When the gauge goes dark, the camera beats a 72-hour-old reading at {15} of {20} sites. While the gauge is online the gauge wins, and we say so." |
| 1:40–2:20 | River Steward agent: a real view-change episode (camera knocked → re-anchored), then a flood replay (rise → wet overlay at the forecast crest → drafted alert → Samuel taps Approve → email arrives) | "A fleet agent watches every camera. When OpenCV says the view moved, it re-registers against its reference bank and either re-anchors or quarantines. When the water rises, it samples faster, draws the NWS forecast crest into the image and drafts an alert. Nothing leaves the system without a human. On {N} fault-injected and real episodes it took the right action {a}% of the time, versus {b}% for fixed rules." |
| 2:20–2:45 | Architecture diagram; `/proof` page; COOL chart | "It runs on AWS Graviton5 with OpenCV's COOL build: {speedup}× on our real pipeline, which is {$} per camera-month to watch the whole fleet. Everything is reproducible from the repo with one command." |
| 2:45–2:55 | Failure gallery montage (night, fog, moved camera) | "It fails at night, in fog, and when a camera is re-aimed. Those cases are flagged, not hidden." |
| 2:55–3:15 | Samuel on camera | "Gauges fail exactly when floods hit. Cameras are already there. RiverSight makes them count." |

**Recording checklist:** 1080p screen capture; mic test; dashboard in light mode; real data only (replays labelled "replay"); end card with the URL and repo link.
