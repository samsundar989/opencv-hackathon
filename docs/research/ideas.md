# E · Idea Scout Report: OpenCV AI Competition 2026 (research as of Sat 2026-10-10)

## Bottom line
- **Build #1 B, working name "RiverSight".** It turns USGS's 1,000+ public river webcams into self-checking water-level instruments, watched by a fleet agent. Only B combines public-domain live imagery, free co-located ground truth at scale, an always-on endpoint refreshed every 15 min, natural OpenCV-5-only depth, a non-template agent loop, a real COOL workload, and an empty lane judges should like.
- **Alternative: #2 G, an OpenCV 4→5 "Porter" dev-agent that ends on COOL.** It has the best odds at the special awards but a weaker "physical AI" impact story.
- **Wildfire (#3) is weaker than it looks.** HPWREN imagery is licensed **CC BY-NC-ND 4.0**, and Pano AI plus ALERTCalifornia already run this in production.

**Facts behind #1**
- [HIVIS](https://www.usgs.gov/mission-areas/water-resources/news/1000-cameras-and-counting) has more than 1,000 active webcams (May 2026).
  - They typically capture every 15 min, daylight only ([USGS-CO](https://www.usgs.gov/centers/colorado-water-science-center/science/camera-installations-collecting-hydrologic-imagery)).
  - USGS aims to put a camera at every one of its 13,000 gauges ([GovTech](https://govtech.com/em/preparedness/usgs-makes-700-cameras-available-to-emergency-managers)).
- Access:
  - Images come through the NIMS API from S3. Downloads need no key, and the imagery is "for the most part" public domain ([NIMS](https://api.waterdata.usgs.gov/docs/nims/overview/), [flowcam](https://connorb.r-universe.dev/flowcam/doc/manual.html)).
  - Gauge data comes from the OGC `continuous` collection. Each query covers at most 3 years, and a free key is needed beyond a few queries per hour ([migration](https://api.waterdata.usgs.gov/docs/ogcapi/migration)).
- Prior art. Cite it and differentiate from it:
  - USGS/Stevens: an $871k computer-vision grant covering about 500 HIVIS cameras ([Stevens](https://www.stevens.edu/news/temimi-and-liu-awarded-usd870-614-united-states-geological-survey-grant-to)).
  - A July 2026 talk on USGS-site stage estimation compares Tenevia/Noema, EfficientNet-B0 regression and staff-plate segmentation ([NWDTW](https://nwdtw2026.sched.com/event/2NP0T)).
  - SAM2+LightGlue reaches about 5 cm with a staff gauge ([arXiv](https://www.alphaxiv.org/abs/2605.14645.md)).
  - Also UNL GRIME AI ([UNL](https://newsroom.unl.edu/announce/snr/19443/104300)) and pyorc LSPIV, which is AGPL ([pyorc](https://github.com/localdevices/pyorc)).
  - None of these is fleet-scale, agentic and publicly benchmarked.
- Impact hook:
  - The July 2025 Central Texas floods killed 139 people, 18 of them in Travis/Williamson/Burnet counties ([KXAN](https://www.kxan.com/independence-day-floods/national-weather-service-releases-new-report-on-deadly-central-texas-floods/amp/)).
  - Running one gauge costs about $13.6k per year (from a 2014 cooperator agreement, [WWALS](https://wwals.net/?p=9783)).
- Naming: OpenCV 5.0 docs list `ptcloud` (Odometry, Volume/TSDF, Octree) plus `geometry`/`calib`/`stereo` instead of `3d`; ICP isn't on the ptcloud page [verify].

## 1. Ranked table (19 ideas)
- All scores run 1–10, higher is better. Crowd 10 means an empty lane; HW 10 means nothing to buy.
- **Ovr** is the expected rubric score out of 100: 3×Tech + 2×Innovation + 2×Impact + UX + Docs + Cloud (per-criterion T/I/R/U/D/C in brackets).
- **Comp** is 0.4·Ovr/10 + 0.1·COOL + 0.1·Agentic + 0.15·Feasibility + 0.05·(Crowd + Judge + Demo + Data + LT).

| # | Idea | Ovr (T/I/R/U/D/C) | COOL | Agent | Crowd | Judge | Demo | Data/GT | Feas | HW | LT | Comp | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|1|**B** River "camera-as-gauge" (HIVIS+gauges)|81 (8/7/9/8/8/9)|8|8|9|8|9|10|8|10|7|8.2|Best all-round|
|2|**G** OpenCV 4→5 Porter + COOL autotune (MCP)|76 (8/8/6/7/8/9)|10|8|8|7|8|8|7|10|7|7.8|Best for special awards|
|3|**A** Wildfire smoke + triangulation (HPWREN/FIgLib)|74 (7/6/9/7/8/8)|7|7|6|7|7|6|5|10|5|6.7|ND license; incumbents|
|4|**D** Phone RGB-D spatial twin → inspection dispatch|70 (8/7/6/7/7/6)|6|7|9|9|5|6|5|6|6|6.6|Phil Nelson's 3D interests; needs depth sensor|
|5|**N** GOES cloud-motion → ERCOT solar-ramp nowcast|64 (6/6/6/6/8/8)|7|6|10|4|8|9|6|10|8|6.7|Trading value; off-theme|
|6|P Coastal flood/rip cams (WebCOOS) + tide gauges|69 (7/6/7/7/7/8)|7|7|9|6|7|7|6|10|6|6.8|Variant of B; API unverified|
|7|O DOT RWIS road-ice cams → plow/salt|64 (6/5/7/7/7/8)|7|7|8|6|6|7|7|10|6|6.7|Variant of B; no snow yet|
|8|M Sky-camera solar nowcast + battery control|66 (7/6/6/6/8/7)|6|6|9|6|6|8|7|8|6|6.6|Well-studied ([arXiv](https://arxiv.org/pdf/2605.03165)); no live ground truth|
|9|J Live DOT traffic cams: ground-plane twin/near-miss|67 (7/5/7/7/7/8)|7|7|7|6|8|7|6|10|5|6.6|Rekor/Miovision; privacy burden|
|10|R Agentic physics lab (video + experiment design)|67 (7/6/6/8/8/6)|4|7|9|6|7|8|7|9|4|6.5|Low impact|
|11|E Active-perception PTZ inspection|67 (7/7/6/7/7/6)|5|9|4|8|6|5|6|6|6|6.4|Good loop, crowded lane|
|12|C Orchard fruit counting/yield|68 (8/5/7/6/8/6)|6|5|8|9|5|6|6|9|6|6.4|Gary Bradski's own field; off-season; NC data licenses|
|13|K Blind/low-vision active-perception assistant|69 (6/6/9/8/7/6)|3|8|6|8|6|5|6|9|5|6.3|Needs real users|
|14|F Bench process-control rig (level/flow + pump)|64 (7/7/5/6/7/6)|5|7|9|8|5|7|5|5|5|6.2|Toy-like|
|15|Q 3D-printer G-code twin, closed loop|65 (8/5/6/7/7/5)|5|8|6|8|5|6|5|5|5|6.2|[Matta](https://matta.ai/research/generalisable-3d-printing-error-detection-and-correction) did it|
|16|T GNSS-denied orchard visual localization|63 (7/6/7/5/6/5)|6|5|10|9|4|6|4|8|6|6.0|Bonsai's own product|
|17|I Retail shelf audit|57 (6/4/5/7/7/7)|6|6|8|4|6|5|7|9|5|5.9|SKU-110K license unclear|
|18|H Racket-sport line calling|58 (7/4/4/8/7/6)|5|5|8|5|6|5|6|8|5|5.7|[SwingVision](https://pulse2.com/swingvision-6-million-funding/) already does this|
|19|L Multi-agent visual SLAM|59 (6/7/5/5/6/6)|6|6|10|9|4|7|2|7|5|5.6|Not credible solo; see [Swarm-SLAM](https://arxiv.org/pdf/2301.06230)|

Rank is my judgment, weighting Ovr and judge fit above Comp. P and O are versions of B on the same engine, so they are kept as fallbacks rather than ranked 3–5.

## 2. Top 5

### #1 B: RiverSight. Public river webcams become calibrated, self-checking gauges, plus a fleet agent
**90-s demo**
- **0–15 s:** the Texas flood hook over a wall of HIVIS cameras.
- **15–40 s:** a live map of 50–100 sites. Clicking one shows:
  - the frame registered with LightGlue, carrying "virtual staff" overlays and the detected waterline;
  - the camera-derived stage plotted against the USGS gauge;
  - a rolling MAE.
- **40–65 s:** a replay of a real flood. The camera flags a rapid rise. The agent then:
  - fetches the full-size frame to "look closer";
  - checks upstream cameras and gauges and the [NWPS](https://water.noaa.gov/about/api) forecast;
  - **draws the forecast crest into the camera image** (inverse stage→pixel map, i.e. physics-informed video prediction);
  - drafts an alert. A human approves it and SNS sends it.
- **65–80 s:** a second trace. A bumped camera makes the registration residual spike, so the agent re-anchors and quarantines its readings. Ice raises a gauge-QA ticket.
- **80–90 s:** an MAE/coverage/COOL cost card and a gallery of failures.

**OpenCV 5 depth**
- `features` ALIKED + LightGlueMatcher register every frame to a site reference. An ablation compares this with ORB/AKAZE across day, night and season.
- USAC/MAGSAC homography.
- Main innovation: **cross-ratio virtual staffs**, a 3-parameter 1-D homography per transect mapping stage to waterline pixel. It is exact for a straight staff or bank line, so 3+ reference heights onboard an ungauged site, and it extrapolates beyond observed stages.
- `calib` handles undistortion and solvePnP ortho-projection wherever there are ground control points or staff plates.
- The `dnn` new engine runs a small water-segmentation ONNX model, distilled from SAM2 labels made on the 5090. ENGINE_NEW, CLASSIC and ORT are compared on Graviton.
- TRUCO contours trace the waterline, and the faster warps do fleet-wide rectification.
- Stretch: DIS-flow LSPIV.
- Optional: a C++ hot path on COOL's C++ SDK. No visible entry uses C++.

**AWS/COOL**
- Pipeline:
  - EventBridge triggers every 15 min and feeds SQS.
  - ECS-on-EC2 c8g runs the COOL Docker image. COOL does not support Fargate.
  - Results go to DynamoDB/S3 and are served through API Gateway/Lambda and a CloudFront dashboard.
- The Bedrock agent's tools are exposed as an MCP server. Human approval uses a Step Functions task token. Tracing uses CloudWatch/X-Ray.
- COOL A/B compares three setups on the real pipeline:
  - c8g + COOL;
  - c8g + pip `opencv-python==5.0.0.93`;
  - c7i x86.

  Metrics are img/s, p50/p95 latency, $/1k frames and a per-stage breakdown. Expect gains in decode and warp but not in the DNN, and say so.
- Hypothesis to test: one c8g.large (about $0.09/h) could cover the whole national fleet.

**Agent loop: the visual evidence changes what happens next**

| Trigger | Action |
|---|---|
|Low registration score|Re-anchor and quarantine the camera's readings|
|Low segmentation confidence (fog, glare, spider web, night)|Fetch the full-size/next frame or a neighbouring camera; fall back to the gauge; open a lens ticket|
|Camera and gauge persistently disagree|Gauge-QA ticket (ice, debris, drift)|
|Rapid rise|Densify sampling, project upstream travel time, check NWPS → human-approved alert|

The agent acts on its own for fetching and recalibration. Anything sent outside the system needs approval.

**Evaluation**
- Data: 50–100 sites × 60–90 days, about 100k image–stage pairs labelled automatically by the gauges.
- Splits:
  - per-site temporal split;
  - leave-site-out for the segmentation model;
  - few-shot onboarding: calibrate on 3–10 points, then test over 60 days.
- Metrics:
  - MAE/RMSE in ft; % within ±0.1 and ±0.25 ft;
  - NSE/KGE; coverage %; px/ft sensitivity;
  - rise-event precision/recall and lead time;
  - false alerts per site-month;
  - agent accuracy on injected faults (camera shift, occlusion, gauge dropout).
- Baselines:
  - persistence;
  - EfficientNet-B0 regression (USGS's approach);
  - Canny/Hough waterline;
  - ablations without registration and without physics.
- Failures to show: night, fog, glare, ice, snow, vegetation, flat banks, wakes.

**Data and licenses**
- HIVIS: mostly public domain. USGS Water Data API: public domain, free key. NWPS: public. Our labels: CC BY.
- Faces and plates on bridge cameras are blurred with YuNet.

**Risks**
- Imagery is mostly daylight-only, while flash floods often come at night.
- At wide rivers each foot of stage covers few pixels, so site selection matters.
- "Why not just use the gauge?" Answer: gauge QA, ungauged or temporary sites, redundancy when gauges fail, and visual context such as an overtopped road.
- Prior art exists; cite it.

**Long-term value**
- A public "HIVIS-Stage" benchmark plus an open-source toolkit.
- Likely buyers: counties and Hill Country camps installing flood cameras, DOTs with low-water crossings, USGS cooperators, and parametric flood insurers ([FloodFlash](https://www.scientificamerican.com/article/upstart-flood-damage-insurer-could-pay-claims-within-hours/)).
- Trading/barge angle: weak, since Mississippi and other gauges already publish stage.

### #2 G: Porter. Agentic OpenCV 4→5 migration that ends in a running COOL workload
**Demo**
- Paste a 4.x repo. The agent records reference outputs under 4.x.
- Under 5.0 it breaks in several places:
  - Haar cascades moved to contrib;
  - the Caffe/Darknet loaders are gone;
  - `VideoCapture.get` returns −1 for unsupported properties;
  - vector/NumPy inputs become 1-D Mats.
- The agent patches the code, for example moving to YuNet on the new DNN engine.
- It then re-runs the code and compares outputs visually, with tolerances for the changed warps, resize and putText. A human approves the exceptions.
- It autotunes threads, DNN engine and input size on Graviton.
- It deploys an ECS service with a live video endpoint and a COOL benchmark.

**OpenCV 5 depth**
- The project covers the whole 4→5 delta. No migration tool exists ([wiki](https://lab.trianta.dev/mirrors/opencv.opencv/wiki/OpenCV-4-to-5-migration)).

**AWS/COOL**
- Untrusted code runs in sandboxed CodeBuild/ECS.
- The c8g COOL image is the deploy target, so the A/B harness itself is the COOL evidence.

**Evaluation**
- Corpus: OpenCV 4.x samples (Apache-2.0) plus permissively licensed repos.
- Metrics:
  - run success %;
  - output-equivalent % (SSIM/keypoint/contour);
  - iterations and minutes per port;
  - speedup.
- Baselines:
  - a naive upgrade;
  - a one-shot LLM rewrite.

**Risks**
- Judges may see it as tooling rather than "physical AI".
- It must clearly show the run–evaluate–adjust loop to qualify.
- Running submitted code is a security problem.

**Failure cases:** contrib-only features (SURF), GUI-only scripts, Caffe models that need conversion.

**Value**
- Open-source traction: the community OpenCV MCP server is inactive ([glama](https://glama.ai/mcp/servers/wxk4xj87fz)).
- A natural fit with OpenCV.org's own priorities. Paid market: niche (one-off migrations, consulting).

### #3 A: Wildfire smoke with geometry-first localization
**Demo**
- A FIgLib replay. Smoke is detected.
- The agent then:
  - pulls the neighbouring cameras;
  - intersects their bearings, adding single-camera ray–DEM intersection;
  - checks FIRMS hotspots.
- A human confirms and the alert goes out.

**OpenCV 5 depth**
- The new-engine DNN detector over stacked frames.
- Flow/MOG2 for plume motion.
- ALIKED/LightGlue to correct camera drift.
- solvePnP/USAC on DEM skyline landmarks.

**Evaluation**
- 315 labelled ignitions.
- Time to detection against SmokeyNet's 3.12 min (F1 82.6) ([paper](https://ar5iv.labs.arxiv.org/html/2112.08598)).
- False positives per camera-day.
- Localization error in km.
- Failure cases: cloud, fog, marine layer, dust, glare, night.
- Other data: USGS 3DEP DEM (public domain), NASA FIRMS (open).

**Licenses: the blocker**
- HPWREN is CC BY-NC-ND 4.0, and commercial use needs a UCSD OIC license ([cc](https://www.hpwren.ucsd.edu/cc.html)).
- ALERTCalifornia says "don't alter the frame" ([credit](https://alertcalifornia.org/?p=1501)).
- Drawing overlays on these images risks the "unlicensed media" rejection rule without written permission.

**Risks**
- Geo-registration is hard.
- Live fires are rare, so the demo would be a replay.

**Value**
- Low. Pano AI has a $44M round and more than $100M in contracts ([SFV](https://salesforceventures.com/perspectives/how-pano-ai-is-building-the-front-line-of-wildfire-defense/)).

### #4 D: Phone RGB-D spatial twin with change-driven inspection
**Demo**
- Two scans a day apart become a TSDF twin.
- The agent finds the changes and dispatches a "close-up at (x,y,z)" task.
- It verifies the close-up and closes the ticket.

**OpenCV 5 depth**
- `ptcloud` ([docs](https://docs.opencv.org/5.0/main_modules/ptcloud_rgbd.html)):
  - Odometry (RGB_DEPTH);
  - Volume (HashTSDF/ColorTSDF);
  - RgbdNormals and findPlanes;
  - raycast/triangleRasterize to render views for a VLM.
- ALIKED+LightGlue to relocalize between sessions.

**AWS/COOL**
- S3 → c8g COOL C++ worker → three.js viewer.
- Measure honestly whether COOL speeds up ptcloud at all.

**Evaluation**
- ATE/RPE on [TUM RGB-D](https://cvg.cit.tum.de/data/datasets/rgbd-dataset) (CC BY 4.0).
- Change-detection precision/recall on our own paired scans.
- Failure cases: textureless or reflective surfaces, moving objects.

**Risks**
- Needs a LiDAR iPhone (Record3D) or a depth camera.
- Python bindings for the classes are unconfirmed (C++ works).
- No live data.
- The impact story is generic.

### #5 N: GOES cloud-motion nowcast of ERCOT solar ramps
**Demo**
- Live Texas cloud field.
- Optical-flow advection 0–120 min ahead.
- Our regional PV forecast plotted against ERCOT's official intra-hour forecast.
- The agent proposes a battery dispatch or paper trade; a human approves it.

**OpenCV 5 depth**
- DIS flow.
- Semi-Lagrangian advection with `remap` (benefits from the faster 5.x warps).
- A residual net on the new DNN engine.

**AWS/COOL**
- GOES from AWS Open Data in the same region → c8g COOL workers every 5 min.

**Evaluation**
- Baselines:
  - IHPPF (NP4-752-CD: 5-min steps, 2 h ahead, by region);
  - smart persistence.
- Ramp-event F1.
- Watch out for curtailment in the actuals ([ERCOT](https://www.ercot.com/gridinfo/generation/index.html)).
- Failure cases: new convective clouds, night.
- Data: GOES (NOAA, public domain), ERCOT public reports, EIA-860 plant locations.

**Risks**
- Remote sensing may not count as "physical vision" for these judges.
- Open Climate Fix and Solcast already do this.

**Value**
- Highest for Samuel's trading; a good follow-on reusing the COOL fleet stack.

## 3. Recommendation
**#1: B.**
- Highest expected score (~81), credible COOL and Agentic shots, lowest data/licensing risk, and a lasting public dataset and toolkit.
- Scope: 50–100 sites, stage only (LSPIV/discharge as stretch goals), one agent, one dashboard.

**48-hour kill test (Oct 11–12)**
- Pull 30 days for 20 sites. Pass if:
  - registration succeeds on ≥90% of frames;
  - MAE is ≤0.25 ft at ≥10 sites using the cross-ratio fit.
- If it fails:
  - reframe B as rise/ice/obstruction event detection; or
  - swap the sensor head to WebCOOS + tide gauges (P) on the same engine.

**Fallback: G**, if Samuel prefers pure software and the special awards, or if NIMS access breaks.

**What would change the ranking**
- **A LiDAR iPhone or depth camera:** D moves to #2.
- **A PTZ camera (about $60–150 [unverified]) at a gauged creek, with permission:** B gains true active perception (the agent zooms to the staff plate), the single best upgrade.
- **An SO-101 arm (about $122 DIY or a $499 kit, [specs](https://roboticscenter.ai/hardware/so-101)) or a 3D printer:** E and Q gain a physical "act", but their lanes are crowded.
- **A real stakeholder:**
  - A county emergency manager, a Hill Country camp or a USGS water science center (nims@usgs.gov) adds 1–2 impact points to B.
  - Orchard access with harvest counts moves C up.
- **Written permission from HPWREN/ALERTCalifornia:** A moves to #2.
- **Trading value over prize odds:** choose N.
