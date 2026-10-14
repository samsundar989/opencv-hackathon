# G — Rival check, OpenCV AI Competition 2026 (changes 2026-10-10 → 2026-10-13)

**Method.** Logged-in Chrome, read-only: ~45 GitHub repo/code searches (repos sorted by updated; code search for HIVIS/NIMS/waterdata strings), repo profiles via the commits JSON route (commit counts, dates, messages) and raw READMEs; Devpost updates, discussions, gallery, and software search (throttles after ~8 queries). Threat 1–5 is my judgement.

## 0. Bottom line
- **Our lane is still empty.** No competition entry reads **water level / stage** from cameras. Nobody in the competition touches USGS HIVIS / NIMS (`usgs-nims-images`, `nims/v0`, `api.waterdata.usgs.gov`): the ~20 repos that do are dashboards, scrapers, an R client and two research pipelines, none entered. ALIKED/LightGlue still only Afterimage (+Parallax). No LSPIV / virtual-staff-gauge / waterline entry.
- **FloodLens is the only lane-adjacent entry moving** (10 commits Oct 13: ECS deploy validated, technical report drafted) — but it is a binary flood/dry classifier on urban video, 75 % accuracy, no stage. AquaTrace, CurvFlood, Streamproof, ripwatch: zero commits since Oct 10.
- **Leaders:** PlumeRank (+33 commits, now 162, audit rounds, no number changes) and DEPTH (+12, now 139, weights published, mAP added) are still sprinting; Afterimage, Blindspot, TREMOR, Hairline idle. New entrants since Oct 10: ~15 GitHub repos, mostly 1–7 commits; two worth noting (Lumen, RentReady Vision). No Devpost organizer activity at all since Oct 10; gallery still hidden; participants 4,848.

## 1. Our lane (water level / flood from cameras)

| Entry | What it does | Commits / last | OpenCV 5 | AWS | Data / eval | Δ since Oct 10 | Threat |
|---|---|---|---|---|---|---|---|
| [FloodLens](https://github.com/joa0lucassi/floodlens-ai) | YOLO11-seg flood/dry on urban video; 1 fps, 960 px, 3-of-5 temporal window; heuristic risk level; FastAPI dashboard | 28 / **Oct 13** | "OpenCV 5" listed; cv2 only for video I/O | ECS Fargate + ECR + S3, end-to-end validated Oct 13 | 20 held-out videos: acc 75 %, P 66.7 %, R 100 %, F1 80 %; "flooded area %" explicitly *not* depth | 10 commits Oct 13: AWS e2e test, interactive S3-mode dashboard, **competition technical report + architecture diagram**, V3 hard-negative experiment (no gain), AGPL | **2** |
| [AquaTrace](https://github.com/dhruvawani17/AquaTrace) | Waterline from city CCTV | 1 / Sep 26 | README claims | README claims | none | none | 1–2 |
| [CurvFlood](https://github.com/bishalg/openCV-flood) | Glacier-lake flood from satellite, C++20 Steger; CDK | 6 / Sep 11 | yes (C++) | CDK, COOL claim | synthetic RMSE only | none | 2 |
| [Streamproof](https://github.com/ToukoUrsin/streamproof) | Stream-photo observation QA | 4 / Sep 21 | yes | yes | "tests a pipeline branch, not environmental accuracy" | none (Devpost page exists) | 1–2 |
| [ripwatch](https://github.com/noufasunkesula/ripwatch) | Rip currents from beach video + agent | 19 / Oct 6 | yes | yes, MCP | none shown | none | 2 |
| [aqua-signal-vision](https://github.com/ntoledo319/aqua-signal-vision) | Water clarity / algae scoring | 8 / Oct 7 | yes | ? | none | none | 1 |
| [WaterGuard](https://github.com/Dupahar/WaterGuard) (new, Devpost page) | Flood impact from Sentinel-1/2 satellite + Bedrock copilot; EC2 + CloudFront live demo | 2 / Oct 10 | OpenCV used, version unclear | EC2, CloudFront, Bedrock | EMS F1 table vs Copernicus EMS | new | 2 (satellite, not camera) |
| [Raksha](https://github.com/Zes-Ar/Raksha) (new) | VGG-16 flood/fire on CCTV "98.9 %", routing solver | 2 / Oct 12 | claims | none | test-set only | new; unclear if entered | 1 |

**Related but NOT entries (prior art / data-source users, worth reading):**
- [lamadipen/OpenFloodAI](https://github.com/lamadipen/OpenFloodAI) — 238 commits, 19 since Oct 10 (Codex-driven). Edge-first river camera flood detection, "mask-based water change" vs a baseline frame, human review; has a **"Download River Images and Video" helper for the public USGS archive** (`ingestion/river_images.py`, `data/reference/rivers/*.json` with NIMS IDs). No AWS, no ML, no OpenCV 5, no competition mention. Not a threat, but it is the closest public codebase to our ingestion layer.
- [hassan1brahim/RUAfloat](https://github.com/hassan1brahim/RUAfloat) — HackRU (Oct 10–11) project: Raritan flood forecast; **checks live USGS HIVIS cameras against the co-located gauge with Gemini + a reference image ("6 of 6 test images matched the gauge")**. Proves the HIVIS-vs-gauge idea is obvious enough for a weekend hackathon, done with a VLM rather than geometry. Not entered.
- [GRIME-Lab/GRIME-AI](https://github.com/GRIME-Lab/GRIME-AI) (`usgs_service.py`, `GRIME2/bin/waterline.py`) and [Ehsankahrizi/TWL_Camera_CrossValidation](https://github.com/Ehsankahrizi/TWL_Camera_CrossValidation) (U. Alabama; ECS Fargate pipeline that archives HIVIS/WebCOOS/511 frames to validate coastal high-tide-flood forecasts) — academic, cite as prior art.
- [ConnorB/flowcam](https://github.com/ConnorB/flowcam) (R client for `nims/v0`, with recorded API fixtures), [Titan2ver/Flood-Sentinel](https://github.com/Titan2ver/Flood-Sentinel) (RPi webcam, Farneback surface velocity, Sep 28), [quintinlevy/Waterline-Detection](https://github.com/quintinlevy/Waterline-Detection) (temporal-noise waterline for a pool dock, Oct 12), [kosei0401/river_camera](https://github.com/kosei0401/river_camera) (cron image dumps). None entered.
- Devpost: "SlackWater" (stream surface speed from a 10-s phone clip, refuses when unsure; 1.59 m/s on a real Geul flood) and "Creek Watch" are **OneAquaHealth IEEE hackathon** entries, not ours. Devpost search for HIVIS/USGS/"staff gauge"/"water level camera" surfaced no OpenCV-competition water-level entry.

## 2. Leaders — what changed

| Entry | Commits (Oct 10 → now) | Last | What changed |
|---|---|---|---|
| **PlumeRank** | 129 → **162** (+33, all Oct 10–12) | Oct 12 | Three "audit" rounds: held-out now stated everywhere as **54 fire *windows* from 41 fires** (not 54 fires); McNemar pairs flagged as not independent (p = 0.18 / 0.25 vs rebased baselines; p < 0.001 vs deployed baselines); "reproduce from fresh clone" timed at ~81 min with 0 mismatch; `make verify` 833 tests; a11y pass. **Headline unchanged: 27/54, median 38.0 min, 2 alerts/camera-window; baselines 18 and 20.** Note repo `createdAt` is 2026-10-09 — history appears re-pushed. |
| **DEPTH** | → **139** (+12) | Oct 12 | Weights published (38 MB, SHA-checked); eval now reports **AP@0.5 0.482 (CI 0.43–0.55), AP@0.5:0.95 0.165** (misses its own 0.70 target and says so); recall promise ≥79 % held at 81.1 %; Stage-1 seabed track on `cv2.Sobel/blur/remap`; review queue ranked by P(real)×severity; approver PIN; counterfactual "detector only vs +OpenCV evidence" (17/27 pins leave error circle). COOL timings still "not yet measured". |
| Afterimage | 126, none | Oct 7 | idle |
| Blindspot | 86, none | Oct 9 | idle |
| TREMOR | 45, none | Sep 23 | idle 3 weeks |
| Hairline | 28, none | Oct 4 | idle; workshop account `rogerkorantenng` has a second entry, **hemowatch** (laparoscopic blood measurement, 27 commits) |
| SteadyFrame / Dialed / Winnow / SightOps / LayerWatch / MargAI / Second Look | none (Winnow +1 README) | Oct 7–10 | idle |
| ADAS-Ready Roads | 51 (+13) | **Oct 14** | technical report, runtime-proof API (OpenCV version, DNN engine, model fingerprints), 60-location "missing markings" test κ = 0.65 → now 3–4 |
| ABC Vision | 24 (+6) | Oct 12 | merged a Nemotron coach agent (also entered in Nebius × NVIDIA) |
| AutoVision | 15 (+6) | Oct 13 | HOG → OpenCV 5 YOLOX, YuNet/SFace; cached real video analyses |

## 3. New entrants since Oct 10 (not in A_competitors.md)

| Repo | One line | Commits / last | Threat |
|---|---|---|---|
| [theMnexus/opencv26-lumen](https://github.com/theMnexus/opencv26-lumen) | Agent merges real-estate exposure brackets (phaseCorrelate, ECC, Mertens, LSD plumb-lines); **live Lambda arm64 URL, 4:24 video, MCP server, 44 MB real test set**, ghost recall ≈0.81 | 4 / Oct 13 | **3** |
| RentReady Vision (Devpost `rentready-vision`; GitHub repo 404/private) | Rental walkthrough video → defect report; **COOL on Graviton4**, Bedrock, SQS/DynamoDB; 94.4 % acc / 94.1 % F1 on frozen 18-video holdout | ? | **3** |
| [soumwadeep/InspectraAI](https://github.com/soumwadeep/InspectraAI) | Industrial inspection vs reference image; P 0.886 / R 0.689 / F1 0.775 on labelled corpus; AWS/COOL explicitly "BLOCKED" | 37 / Oct 13 | 2 |
| [cloudlabworks/guetteur](https://github.com/cloudlabworks/guetteur) (Team Drift) | Depth-only lookout with "receipts"; synthetic OAK-D scenes only, SAM draft never deployed | 7 / Oct 13 | 2 |
| [annarose14/adas-ready-roads] | (in A list; upgraded, see §2) | | |
| [darksagae/agrof-vision](https://github.com/darksagae/agrof-vision) | Leaf tissue map / crop quality gate, Lambda adapter, 21 tests | 6 / Oct 11 | 1–2 |
| [Vcode2407/opencv-clearpath](https://github.com/Vcode2407/opencv-clearpath) | Floor-change measurements, fixtures only | 8 / Oct 11 | 1–2 |
| [krittikanandy06-ctrl/crackpulse](https://github.com/krittikanandy06-ctrl/crackpulse) | Crack width (sub-pixel FWHM) + vibration | 11 / Oct 10 | 2 |
| [habib-analyst/SonoSight](https://github.com/habib-analyst/SonoSight) | Breast-ultrasound Grad-CAM, 87 % on 156 images | 2 / Oct 13 | 1 |
| [liutingqiu/opencv5-aws-agentic-vision-sentinel](https://github.com/liutingqiu/opencv5-aws-agentic-vision-sentinel) | "Sub-20 ms telemetry" + EventBridge/SQS; HTML, 1 commit | 1 / Oct 11 | 1 |
| [vladimirjoseph36-png/inventory-qc](https://github.com/vladimirjoseph36-png/inventory-qc) | Inventory QC on Lambda + S3 (also Devpost) | 3 / Oct 12 | 1 |
| [EkalavyaLearn/sitewatch-edge](https://github.com/EkalavyaLearn/sitewatch-edge) | PPE screening, "sanitized judge archive" | 2 / Oct 11 | 1 |
| [rogerkorantenng/hemowatch](https://github.com/rogerkorantenng/hemowatch) | Workshop's 6th entry (surgical blood) | 27 / Oct 3 | 2 |
| blucca "Capture Loop" ([dockproof](https://github.com/blucca/dockproof) branch) | Label close-up retake loop on Lambda; posted a peer-test thread on Devpost | 10 / Oct 13 | 2 |
| Gaut-raj/OpenCV-AI-Competition, hacky-man/OpenCV_AWS_Competition-2026, owat95/opencv-agentic-vision-aws | empty initial commits | 1 / Oct 12 | 0 |
| Devpost-only new pages: VisionGuard AI (na4wop), ListingLens, Agentic Visual Inspector (ronisaguey) | duplicates of known repos or thin | | 1 |

**Count.** GitHub: "OpenCV AI Competition" 49 repos (32 for "…2026"), "OpenCV 5" pushed since Oct 10: 18. Devpost "opencv 5 aws" search: **212 projects (196 on Oct 10, +16 in 3 days)**. Adding the above to the Oct 10 inventory gives **~125–130 visible entries**; the quality-gate/inspection pattern still dominates the newcomers (Lumen, RentReady, Inspectra, ClearPath, Capture Loop, Inventory QC).

## 4. Devpost
- **Updates:** still only the 29-day-old "AWS Compute Grant notifications sent" post. Nothing new.
- **Discussions:** one new topic since Oct 10 — "Capture Loop: phone retake trial + OpenCV peer review exchange" (Oct 11, an entrant soliciting phone tests; says their pilot runs to Nov 10). **No organizer replies since Oct 10.** Still unanswered: *"Do the services need to be always-on or is a 2–5 min cold start acceptable / will judges weigh the video instead?"* (23 days old, 0 comments), under-18 eligibility conflict (9 days, 0 comments), different AWS account, grant status. Answered earlier by Phil Nelson (Manager): simulated data allowed; teams without an August proposal are eligible; new Slack link posted. No thread on multiple entries.
- **Participants: 4,848.** Project gallery: "The hackathon managers haven't published this gallery yet" — still hidden; filter sidebar shows the two sponsor prizes (Best Use of COOL, Agentic Vision).

## 5. Implications for RiverSight
1. Lane confirmed open 13 days out; the only mover (FloodLens) does classification, not measurement, and FloodLens's own README says depth "would require additional calibration" — exactly our projective pixel→stage model. Cite it as the contrast.
2. Cold-start question is unanswered: keep an always-on `/judge` page (every leader has one) rather than hoping the video suffices.
3. RUAfloat and TWL_CrossVal show the "compare camera to co-located gauge" framing is easy to think of; our edge must be the **quantitative stage estimate with error bars vs the gauge across many sites**, not the idea.
4. PlumeRank's last three days were all audit/reproducibility (window-vs-fire wording, McNemar caveats, timed fresh-clone reproduction). Judges will see that standard; budget time for the same on our eval.
5. COOL award still has no rigorous entrant; DEPTH says its COOL timings are "not yet measured", Hairline (1.11×) remains the bar.
