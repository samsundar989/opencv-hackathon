# A — Competitor intelligence, OpenCV AI Competition 2026 (as of 2026-10-10)

**Method.**
- **GitHub:** 60+ repo and code searches in the logged-in browser, about 1,350 repos. I scanned the READMEs of the ~840 updated since Aug 12 and profiled ~115 for commits, tests, IaC and COOL files.
- **Other sources:** Devpost project pages and search (throttled after ~60 results), the Hugging Face Spaces API, X, LinkedIn, YouTube, dev.to and Medium.
- **Reddit** is blocked by the browser's safety policy and was not checked. X, YouTube, dev.to and Medium had no competitor projects; demo videos are unlisted.
- Threat scores (1–5) are my judgement; [unverified] means inferred. The full inventory is in the Appendix.

## 1. What changed since yesterday
1. **About 110 entries are visible, up from ~26:** ~95 GitHub repos, ~10 Devpost-only pages, 1 Hugging Face Space and 2 stealth LinkedIn posts.
   - Devpost search for "opencv 5 aws" returns 196 projects.
   - Every competition page I sampled already has a video, so many entries look ready to submit.
2. **The bar has risen sharply.** At least 10 entries have a live endpoint, a video, and a real-data evaluation with baselines or ablations: PlumeRank, Afterimage, Blindspot, TREMOR, Dialed, SteadyFrame, Hairline, Second Look, DEPTH, ABC Vision.
3. **Lanes that were empty now have entrants:**
   - wildfire: PlumeRank, top-tier
   - remote sensing: Places Not Pixels
   - sports: ABC Vision, Tactiframe, 442ools
   - flood / water: AquaTrace, FloodLens, CurvFlood
   - drone 3D: FlightPrint
   - developer agent + COOL: AutoVision
   - C++: CurvFlood
   - retail shelf: StoreVision AI (Devpost only)
4. **One "workshop" runs at least 5 entries** from one monorepo (`packages/servicekit`, `packages/visioncore`, `infra/apprunner.sh`) under different accounts.
   - Identified: Keepout, Preempt, Scopewatch and Hairline.
   - Hairline's README says it is "one of five entries built on a shared foundation".
5. **Some projects are also entered in other hackathons:** HomeworkHawk and Sherpa (Nebius); ABC Vision and Care Ladder ("simulated Alexa+").
6. **Activity since Oct 8:**
   - Active: PlumeRank (35 commits on Oct 10 alone), SightOps (20), SteadyFrame (13), DEPTH (12).
   - Idle for 6 days or more: Winnow, TREMOR, Kinevra, Second Look, Care Ladder, the workshop entries.

## 2. COOL: new hard facts (most important finding)
**There is now an official benchmark:** [opencv/COOL-Benchmark](https://github.com/opencv/COOL-Benchmark). It has an EC2 orchestrator, a web UI and an MCP server pushed to each instance.
- Its changelog (v2.0.0, 2026-04-21) claims **3.22× on average across 20 functions, but against pip OpenCV *4.13*** on m8g.xlarge:

| Function | Claimed speedup |
|---|---|
| Laplacian | 10.5× |
| adaptiveThreshold (mean) | 7.7× |
| Scharr | 4.25× |
| calcHist | 4.1× |
| cvtColor | 4.0× |
| Sobel | 3.3–3.7× |
| matchTemplate | 2.6× |
| Otsu threshold | 2.4× |
| resize | 2.4× |
| bilateralFilter | 2.2× |

**The fair baseline is much stronger.** Hairline confirmed that the pip `opencv-python` 5 wheel for Arm **already includes KleidiCV 26.03**.
- So COOL's gains over pip-5 on the same Graviton instance are small.
- COOL-versus-x86 comparisons measure the CPU, not the library.

**Version trap.**
- Hairline's AMI, "COOL-Graviton4-v2-AMI-prod" (built 2026-04-22), reports **OpenCV 4.14.0-pre, not 5**.
- Blindspot and TREMOR report COOL as "5.1.0-dev", presumably the v3.1 listing [inferred].
- Practical gotchas: `/opt/cool` venvs only find `cv2` after `activate`; the root volume is 50 GB; Marketplace terms must be accepted in the console or launch fails with `OptInRequired`.

**Measured results so far:**

| Entry | Result |
|---|---|
| Hairline | 1.11× end to end (adaptiveThreshold 1.73×, findContours 1.00×); 4% cheaper per frame after the fee |
| TREMOR | 1.26× (5.21 → 4.14 ms/frame) |
| Blindspot | COOL **8.7% slower** than stock 5.0 on a DNN-heavy pipeline |
| ForgeSight | COOL 6% slower |
| PlumeRank | Declined COOL |

- **Claims with no provenance:** UrbanSense-AI, kbytehub0x/visionguard, Aegis-5000, 442ools and CurvFlood. These are most likely Graviton-vs-x86 comparisons, or invented.
- **Who leads the COOL award:** Hairline (method), TREMOR (speedup), DEPTH (only labels a run COOL if `cv2` loads from `/opt/cool`), Blindspot (honest negative result).
- **Nobody has yet** built a pipeline around COOL's fastest operations, used the C++ SDK, or used the ECS container.

## 3. Deep dives: what the winning bar looks like
| Entry | What it does | OpenCV 5 depth | AWS | Evaluation | Delivery / track | Threat |
|---|---|---|---|---|---|---|
| [PlumeRank](https://github.com/edycutjong/plumerank) | Ranks 62 HPWREN wildfire cameras, 2 alerts per camera-night | 23 calls counted by a script, incl. `phaseCorrelateIterative`, USAC_MAGSAC, DIS optical flow, `dnn` ENGINE_NEW | t4g.small, S3, CloudWatch alarms | Held-out 27/54 fires, median 38 min, vs like-for-like baselines 18/54 and 20/54; ablations; dated "what we got wrong" | [Live](https://live.plumerank.edycu.dev) with /judge page; CodeQL; 129 commits. **Overall only** | **5** |
| [Afterimage](https://github.com/gmassello/afterimage) | Inspection agent that remembers each asset (solar panels) and compares every photo with its stored baseline | ALIKED, LightGlue, ANNIndex, FontFace — all OpenCV 5-only | Lambda arm64, DynamoDB, S3, OIDC | 29 scenarios (18 real photos): branch accuracy 0.86, defect F1 0.85; ablated against ORB-only and no-memory | Live endpoint, 3:07 video, [Devpost](https://devpost.com/software/afterimage-ibp376). **Agentic** (MCP + Gemini; code makes the decisions) | **5** |
| [Blindspot](https://github.com/Kim-Hakseong/blindspot) | Finds the capture conditions under which a detector fails | Physically modelled blur, rolling shutter, noise and codec effects; MTF50; cv::dnn | 14 services via CDK: Batch, Fargate, Step Functions, X-Ray, … | Deterministic replay; a test bans LLMs from the judgement path; 3-way COOL benchmark | Devpost + video. Overall + COOL | **4** |
| [TREMOR](https://github.com/TusharTechs/tremorcv) | Machine vibration from handheld video | Sub-pixel `phaseCorrelate`; reported a 5.0.0 bug | EC2 c8g with COOL | Agent accuracy flat at 79.2% however badly the camera is aimed | Live EC2, video, MCP with 8 tools. COOL + Agentic | **4** |
| [DEPTH](https://github.com/madhesh60/depth) | Lost fishing gear in side-scan sonar → cleanup plan a human approves | cv2.dnn running YOLO11s | EC2 Graviton with COOL | Calibrated tiers (at least 79% of pots reach a human; held at 81.1%); blinded audit; withholds each OpenCV output to show it matters; honest F1 0.41 | Plans re-survey passes; OGC API, MCP. Agentic + COOL | **4** |
| [SteadyFrame](https://github.com/SrijaVuppula/SteadyFrame) | Finds flashing hazards in video, fixes them, verifies the fix | LUT, boxFilter, accumulateWeighted | Lambda, SQS, Fargate, Bedrock, CDK | Per-second F1 1.000; EA's IRIS test videos 18/18; 0 of 551 control seconds flagged | Live on CloudFront. Agentic | **4** |
| [Dialed](https://github.com/RohanGlitched/dialed) | Reads an analog gauge from a phone photo; agent logs it, asks for a retake, or holds a work order | warpAffine straightening, cv.dnn OCR | Lambda, Bedrock Nova, CloudFront | Share read within 2% of scale: 99.4% (200 rendered), 97.6% (100 bad photos), 91.7% (37 real) | Live, video, Devpost. Agentic | **4** |
| [Places Not Pixels](https://huggingface.co/spaces/cp500/team-picasso-opencv-ai-competition-2026) | Satellite images become outlined shapes with stored facts; plain-English questions get exact answers | OpenCV 5 in WebAssembly, cv.dnn, SAM 2.1 | Graviton benchmark only [unverified] | Exact answers verified, e.g. 1,369/1,369 containment checks | Hugging Face Space, video, report PDF. Overall | **4** |

**Also strong:**
- [Hairline](https://github.com/christin09110-stack/hairline) (4 for COOL; live endpoint).
- [ABC Vision](https://github.com/ekyo0224/abc-vision-mcp) (3–4): badminton coaching MCP server with real usage.
- Second Look, Winnow and LayerWatch (3–4).
- At 3: MargAI, ADAS-Ready Roads, Argus, Care Ladder, Wildlife Monitor (precision 0.959 / recall 0.879), and the workshop's Keepout, Preempt and Scopewatch.

**What the strongest entries all have:**
- an always-on endpoint with a /judge page
- a video under 5 minutes
- held-out real data with like-for-like baselines and ablations
- headline numbers checked automatically by tests
- infrastructure as code with OIDC deploys
- responsible-use and AI-use documents
- a table of "OpenCV 5 call → what it does → without it".

**OpenCV 5-only features are still rare** (per GitHub code search):
- ALIKED / LightGlue: only Afterimage and Parallax.
- ENGINE_NEW: PlumeRank, SiteSentry, Wildlife Monitor.
- **No competitor uses** the `3d` module (TSDF/ICP), multi-camera `calib`, or a VLM inside the DNN module.

## 4. Lane map
**By domain:**

| Domain | Entries |
|---|---|
| Industrial / asset inspection & QA | ~30 |
| Safety / smart city / traffic / road | ~22 |
| Documents / commerce / media QA | ~18 |
| Health / accessibility | ~16 |
| Environment / agriculture | ~14 |
| Spatial / 3D / robotics | ~9, all weak |
| Sports | 3 |
| Developer tools | ~4 |

**Agent-loop patterns:**

| Pattern | Share |
|---|---|
| Quality gate → retake / escalate | ≈55–60% |
| Detect → verify → human approval → alert | ≈25% |
| Memory / baseline comparison | 1 (Afterimage) |
| Planning the next measurement or survey | ~4 (DEPTH, TREMOR, AegisLand, Steropes) |
| Expose MCP tools | ~15 entries |

The LLM is mostly Claude or Nova on Bedrock.

**The lanes you asked about:**
- **Wildfire / smoke:** taken by PlumeRank. It replays an archive (HPWREN FIgLib), not live feeds.
- **River / flood from cameras:** four weak entries.
  - [AquaTrace](https://github.com/dhruvawani17/AquaTrace): waterline from city CCTV; 1 commit [unverified entry].
  - FloodLens: 75% accuracy on 20 videos.
  - CurvFlood: satellite images, C++.
  - Streamproof.
- **Agriculture / orchard yield:** no orchard or yield entry.
  - CropCare: 5-person team, 3 commits.
  - AgroDron: README only.
  - reekh: ESP32 wildlife deterrent [unverified].
- **Spatial digital twin / 3D reconstruction:** weak.
  - [FlightPrint](https://github.com/LonelyGuy12/FlightPrint): drone video → 3D.
  - Spatial Maintenance Copilot: still a prototype.
  - The "digital twin" repos are 2D.
- **SLAM:** one, [3d-stimulator](https://github.com/bharatsachya/3d-stimulator), a monocular SLAM on the TUM dataset, running on EC2 [unverified entry]. No multi-agent SLAM.
- **Sports analytics:** ABC Vision (has real users), Tactiframe (4 commits), 442ools.
- **Retail shelf audit:** only [StoreVision AI](https://devpost.com/software/storevision-ai), a Devpost page with no repo.
- **Live traffic cameras:** none. Every traffic entry uses recorded or synthetic video.
- **Developer agent / MCP for COOL:** half open. [AutoVision](https://github.com/techcto/autovision) does not claim the agentic awards; the official benchmark already ships an MCP server.
- **Active perception with a moving camera:** only simulated or claimed (AegisLand drone landing, Steropes, Aegis-5000). No real pan-tilt, robot or drone hardware.
- **Physics-informed video prediction:** none. The closest is Watch→Imagine→Act.

**Stealth entries on LinkedIn:**
- Prakhar Goel (USC): multi-agent system, not shared yet.
- Charles Prosper: Places Not Pixels.
- Najmun Nahar Hira: InspectAgent.

## 5. Implications for us
1. **First place needs PlumeRank-level evidence.** PlumeRank (overall) and Afterimage (Agentic) are the favourites; both are solo and finished early.
2. **Do not build an inspection quality gate.** That pattern is about half the field.
3. **The COOL award is winnable:**
   - Run COOL 5.x against pip-5 with KleidiCV on the same instance.
   - Build the pipeline around COOL's fastest operations.
   - Add a C++ SDK arm and full provenance.
   - The bar to beat is Hairline's 1.11×.
4. **Lanes that are still open:**
   - live public camera feeds processed on Graviton
   - physics-informed video prediction
   - real actuation (pan-tilt camera, robot)
   - multi-view 3D built on OpenCV 5's `3d`, `calib` and `features` modules
   - orchard or yield counting.

## Appendix — inventory of visible entries (repo · domain · notes · threat 1–5)
**Inspection / equipment QA**
- gmassello/afterimage · solar/asset memory agent · see §3 · 5
- Kim-Hakseong/blindspot · robustness boundaries · see §3 · 4
- TusharTechs/tremorcv · vibration · see §3 · 4
- christin09110-stack/hairline · crack width (mm); workshop; best COOL methodology; live c8g.large · 4
- RohanGlitched/dialed · gauges · see §3 · 4
- rkb32/winnow · dataset QA; CloudFront live; 34 commits, idle since Oct 3 · 3–4
- Pytro001/layerwatch · metal 3D-print layers; Lambda plus a COOL path on c7g; Bedrock Claude; macro F1 0.95; Devpost · 3–4
- yablokolabs/sightops · appliance panel diagnostics; actively developed; Bedrock · 3
- neemlama/opencv-visionguard (ForgeSight) · steel defects; COOL on OpenCV 5; retracted an inflated ablation number · 3
- najmunnaharhira/…-powered-by-AWS (InspectAgent) · machined parts; Lambda on Graviton; SAM; synthetic evaluation · 2–3
- Lukols-Dev/Spatial-Maintenance-Copilot · spatial guidance; AWS grant; ECS Fargate · 2–3
- Steven3-art/repairmind-edge · electronics · 2
- kagithamanoj/visionguard · inspection with guardrails · 2
- vasujunior7/Parallax · refuses to answer when unsure; uses ALIKED · 2
- BryceWDesign/IX-VisualAuthority · 2
- pmartins87/AeroGuard · 136 commits · 2
- harsharajkumar-273/pixel-gaurd · bandit policy; MCP · 2
- FranklinNexus/traceloop · 1–2
- Sayandevxyz/VisionForge · 3-person team · 1–2
- karimunnisa-123/axon · Gemini, MCP · 1–2
- 0xkodoh/vision-nexus · 1–2
- dlane25/wellsight · 1
- umeshianjana/PCB-Defect-Inspection-Agent · 1
- nandini9690/OpenCV-AI (tile QC) · 1
- mapoca1219/Aegis-5000-Vision-OS · unverified claims · 1
- ronisaguey-ux/opencv-agentic-inspector · 1
- Stewartsson/agentic-vision-inspector · 1
- vsmithreyan-rgb/mechsight-guardian · 1
- genesiscode2026/velqiris-opencv-aws-vision · 1
- Akshit-Singh-00/secondcut · cardboard-cutting recovery · 2
- Cubiczan/fieldsight (also icohangar-ops) · jobsite inspection · 1–2
- Devpost only: HSAAI Vision Agent, Quipu Vision, Authority Vision · 1

**Safety / surveillance / city / road**
- madhesh60/depth · sonar · 4
- himanshu748/marg-ai · dashcam road damage · 3
- annarose14/adas-ready-roads · lane-marking visibility · 3
- renigat7-cpu/argus-agentic-video-triage · long-video triage · 3
- rogerobeng77-oss/keepout · danger zones; workshop · 3
- chinesepowered/hack-opencv2 · traffic near-misses · 2–3
- jiarong0423/jiarong0423-road-marking-conformity · 2–3
- solanaminter/siteguard-agent · construction safety · 2
- arindewangan/sitesentry · construction safety · 2
- Dmgar/project_Flowsense · emergency-vehicle routing · 2
- noufasunkesula/ripwatch · rip currents; early sprint; MCP · 2
- gcjordi/ciberia-visionguard-opencv26 · 2
- kbytehub0x/visionguard · 2
- ShinyDataTech/UrbanSense-AI · 2
- tinexu/sidewalk (Reachable) · 2
- skanifegowoh-sudo/sanctus-tv-visual-reliability-agent · 2
- Cyberchopin/aegisland-agentic-vision · 2–3
- wyyyrdx/Steropes · 2
- Devpost only: Mat(a)Mu (citizen road reports) · 2
- At 1–2: dl88jing/northbridge-watch, wasko1984/visionguard, PionneerZ/quietguard-vision, neerajojha1855/agentic-video-redaction-system, anhminhzui-dev/opencv-entry, dnya707/TrafficReason, MuzammilCk/pro-to-type, yashrajshrestha/ring-clip-agent, Abhishek-200/VisionNOC (no AWS access), TrafficAgent-AI (Devpost only)

**Health / accessibility**
- jo2980958-hub/preempt · bed exit; workshop · 3
- rogerkorantenng/scopewatch · laparoscopy; workshop · 3
- pamu512/opencv-care-ladder · eldercare escalation; video v5; ECS · 3
- nishnarudkar/Kinevra · rehab · 3
- SrijaVuppula/SteadyFrame · flash hazards · 4
- dungnotnull/DoseGuard · pill organiser · 2–3
- rohnringo3-tech/medlens-vision · medicine labels and pill counts · 2
- GVethaNarayanan/RaktaScan · anaemia screening · 2
- Dharun235/tamil-fingerspelling-assistant · 2
- fsafva13-coder/lumen · liveness · 1–2
- At 1: NeuroViu (Devpost), ferrangarcia33/fall-detection-ai, MellowVellow/opencv-fitness-rpg, Riippex/kinetiq-v-vision, snehassneha4578-collab gesture project

**Documents / commerce / media**
- guptachetan1995/opencv (Second Look) · receipts · 3–4
- Zaichek/homeworkhawk · homework grading · 2–3
- apn201/Arpi · damaged barcodes · 2–3
- MOHAMEDPARVEZMAHAROOF/formlens · forms · 2
- rajab-rajab/pageready · document scans · 2
- agentaiventure-dot/claimlens · claim photos · 2
- williamleewilliam1-star/babydov-listinglens-agent · catalogue photos · 2
- exochard/menu-photo-to-website · 2
- vansyson1308/aistockcounting (TrayAgent) · 2
- AashneeSethi/QRensic · QR fraud · 2
- michi883/stage-ready · performer video · 2
- mictopraise/Visionguard-qa · video QA · 2
- tzh476/opencv-evidence-locker · 2
- hungtruongOwolf/sherpa · screen tutor; Nebius entry too · 2
- At 1–2: BxRKings/damage-lens, gil906 TrayScout, YK-StudioPM/minarai, ondmindmanagement-hub/bolt-vision-gate, StoreVision AI (Devpost only)

**Environment / agriculture / earth**
- edycutjong/plumerank · wildfire · 5
- Places Not Pixels · remote sensing · 4
- el-informatico/wildlife-monitor-ext · camera traps · 3
- dhruvawani17/AquaTrace · flood · 2–3
- bishalg/openCV-flood · glacier floods; C++ · 2–3
- joa0lucassi/floodlens-ai · urban floods · 2
- ToukoUrsin/streamproof · stream observations · 2
- samarmahore48-glitch CropCare · crop disease · 2
- deepak427/reekh · wildlife deterrent · 2
- ntoledo319/aqua-signal-vision · water quality · 1
- Marco1567/agrodron-flora-plus · 1
- mohammad-oghli/Wildlife-Agentic-Vision · 1

**Spatial / 3D / robotics**
- LonelyGuy12/FlightPrint · 2–3
- bharatsachya/3d-stimulator · SLAM [unverified entry] · 2
- ahpa5246-lgtm/cv-competition (Watch→Imagine→Act) · 2–3
- Vigneshcit2006/visiontwin-ai · 2
- darrenthanawinn-ux/SpatialDigitalTwin · 1
- Pragati-7210/BlueprintMind · 1

**Sports**
- ekyo0224/abc-vision-mcp · 3–4
- ousssamarahmani/Tactiframe · 2
- Insight14/442ools · 2

**Developer tools**
- techcto/autovision · developer agent + COOL · 2–3
- he-yufeng/visiongate-ci · says it is "not a competition result" · 1
- official reference: opencv/COOL-Benchmark
