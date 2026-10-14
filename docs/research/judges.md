# B — What these judges and organizers will reward (OpenCV AI Competition 2026)

Compiled 2026-10-10 from YouTube transcripts (OpenCV Live #215, #220/launch clip, #221, #222, #224, #226–228; 2023 winners show), Bradski interviews, OpenCV core-team meeting notes, AWS blogs and Devpost. Video statements are paraphrased with approximate timestamps. [unverified] = inference.

## 1. Organizer signals (dated)

**OpenCV Live #215, *COOL: The Official Cloud Version of OpenCV* (Jul 2, 2026)** — guests Frantz Lohier (AWS), Abhishek Gola and Om Rope (OpenCV). https://www.youtube.com/watch?v=YTMqfx-a9cw
- Satya Mallick (~1:09): personally wants OpenCV 5 inside an agentic loop on Graviton/AWS, but judges will score solution quality, problem choice and execution, not organizers' pet topics.
- Satya (~1:02): OpenCV hasn't started its own agentic integration; competition entries will steer that roadmap.
- Frantz (~1:03): the COOL benchmark framework is open source; he urged teams to benchmark their own workloads. His charts showed COOL/Graviton giving ~10× the images-per-dollar of an NVIDIA L4 instance running the same CPU workload (~50:00).
- Phil Nelson (~1:07:48): wants projects that matter to people — human-assistive devices and human safety.
- Phil (~1:39), on shallow AI-built work: "Anybody can get that from Claude." Satya stressed depth over claims, noting deep learning can look fine even with broken preprocessing.

**Launch (~Aug 13; #220 + clip).** https://www.youtube.com/watch?v=GJgE3TJMDDQ · https://www.youtube.com/watch?v=5lgfzHj9Z9A
- Frantz: Graviton preferred; physical AI, robotics or any computer-vision vertical welcome.
- Satya: the suggested areas match what independent judges already lean toward, so work there will be well received.
- **Satya's explicit challenge:** beat COOL using standard OpenCV and get a guaranteed mention on the webinar (not a prize). His suggested route is long-running optimization agents, citing an AWS engineer with a high-frequency-trading background whose agents keep tiny gains that add up to 10–30%.
- Satya would love a developer agent integrating COOL with Codex or Claude Code. He called video prediction now reachable, and said the suggestions come from BigVision consulting problems.
- Phil: judges are himself and Gary, with more to be announced individually. Winners appear on OpenCV Live Nov 10 and are invited back to explain their builds.
- AI-written code is fine if you can explain how it works. The official video description requires computer vision as a core component, not a bolt-on.

**#221 (~Aug 20):** 473 sign-ups, ~120 proposals. Phil: solo is possible but hard; teams do better. Grant review weighed team, experience, problem and solution. https://www.youtube.com/watch?v=e5X8dd22D4M

**#222 (Aug 27):** ~200 grant proposals, 725 participants. Phil is eager for COOL+AWS builds; success could bring more, bigger AWS-powered competitions — **organizers need showcase wins for AWS.** https://www.youtube.com/watch?v=PApvTB8O8hE

**#223–228 (Sep–Oct):** no new judging guidance. #228 promoted OpenCV Enterprise; Devpost is now a silver member, Qualcomm gold.

**Rules nuance:** COOL and agentic methods earn Overall credit only to the extent they improve the project. Judges may reject entries that misstate results, benchmarks or the role of human review. https://opencv26.devpost.com/rules

**Meeting notes:** COOL averages ~1.2× over OpenCV 5.0; the Graviton 5 build showed +23% across 102 ops (Aug 19). https://github.com/opencv/opencv/wiki/2026 · mirror with August entries: https://lab.trianta.dev/mirrors/opencv.opencv/wiki/2026

## 2. Gary Bradski

**Roles**
- OpenCV founder and president.
- CSO, Bonsai Robotics: vision-based autonomy for specialty crops in dust, darkness and without satellite positioning; acquired farm-ng in Jul 2025; expanding into mining and defense. https://www.accessnewswire.com/newsroom/en/computers-technology-and-internet/bonsai-robotics-announces-deep-bench-leadership-to-accelerate%c2%a0-ai-1063705
- Stanford research from summer 2026 on next-generation VLMs, possibly JEPA-style (joint-embedding predictive) models; spatial-AI work with Edgar Riba (Kornia).
- Web Summit Misty West HardTech award, May 2026, for commercial deployment of AI and computer vision in robotics. https://www.youtube.com/watch?v=mFVT-Ucd9u4
- OSCCA speaker, May 4, 2026. https://opencv.org/oscca/

**Technical interests, 2025–26 (meeting notes)** https://lab.trianta.dev/mirrors/opencv.opencv/wiki/2025
- A classical-first SLAM project for Google Summer of Code.
- DISK and LightGlue features; camera localization.
- VLMs assisting 3D reconstruction, with Gaussian splats for the rigid scene.
- xfeat and ALIKED as free alternatives to SuperPoint.
- **Code assistants that write OpenCV code or optimized internals.**

**Display Week interview (May 2026)** https://www.youtube.com/watch?v=Er9zYTFJG_o
- Wants real autonomy; suspects staging behind teleoperated robot demos.
- The big shift is AI in the physical world, not chatbots; agriculture's real constraint is labor.
- Robots need multiple sensors, and at least two information sources for safety.
- JEPA-style semantic models are the most promising direction.
- OpenCV's DNN module should run optimally on Arm and RISC-V.
- Privacy: detachable cameras to remove creepiness.

**On competitions (GOSIM interview, Dec 2024)** https://www.youtube.com/watch?v=Zf695fTGrig
- Competitions should tackle real problems, not tidying-robot stunts or already-solved web-image tasks.
- His model challenge: autonomous plant monitoring across thousands of test plots for climate adaptation.
- Entrants should build on a common substrate so results are comparable.
- Business advice: get real fast, involve customers, keep it simple; avoid copycat LLM fine-tunes.
- Wants an OpenCV-aware LLM that suggests operators.
- Frames a spatial world model as what/where/why, with SLAM as the model problem for continual learning.
- Ethics: a shared incident database plus simulation regression tests before deployment.

## 3. Phil Nelson

**Background:** at OpenCV since 2021; previously Occipital (3D sensing) and BrandYourself; based in San Francisco. Runs OpenCV Live, OSCCA, sponsorships and competitions, including the 2025 bin-picking challenge with Intrinsic. https://theorg.com/org/opencv/org-chart/phil-nelson

**2026 OpenCV Live topics** (https://www.youtube.com/@OpenCVOfficial/streams):
- SLAM and visual positioning (VPS); calibration (MetriCal/AutoCal, Luxonis); 6-DoF pose (Intrinsic).
- MolmoMotion 3D trajectory forecasting; drones (GPS-denied, STEM); anomaly detection.
- OpenCV 5/HAL/COOL; Granite Vision and Docling; synthetic inspection data.
- Robot-fleet reliability (pinned builds, heartbeats); OpenCV-to-Isaac Sim physical AI.
- **Pattern:** 3D/robotics, VLMs inside real workflows, production reliability.

**Taste from judging (2023 winners show)** https://www.youtube.com/watch?v=T6AMa_at2N8
- Simple illustrations help a lot.
- FREISA was his model submission: all code, models and printable parts published, so anyone can rebuild it.
- The exoplanet entry won praise as focused and scientific, using OpenCV's SIFT and homography for real science.
- Assistive and safety projects recur every year, so an entry must stand out; pick-and-place robot arms are a trend.
- Prefers ~3–3:30-minute videos (FREISA ran 4 s over five).
- Two entries that previously lost while unfinished came back finished and reached the top 7.

**Pet peeves:** teams that can't explain their code; generic LLM-grade output; over-long videos.

## 4. OpenCV and AWS commercial interests

**OpenCV**
- COOL is a revenue line; roadmap is Graviton 2–5, then GPUs, AMD and Intel. Agentic integration waits on competition ideas.
- OpenCV Enterprise (long-term support, certified binaries, security patches) is the top homepage banner.
- OpenCV 5 adoption: the new DNN engine and LLM/VLM inference.
- OpenCV University (incl. a free VLM Bootcamp), OpenCV.ai/BigVision consulting, partnerships with Qualcomm, AMD and Roboflow. https://opencv.org/
- Satya's lens: VLMs plus classical computer vision; precise, real-time computer vision for drones, inspection, manufacturing, agriculture (guidance, ripeness, weed targeting) and pathology.

**AWS**
- Graviton price-performance versus GPUs; COOL scaled out across instances and containers.
- Physical AI blog themes: robotics, sim-to-real, world models, OpenUSD and SDMA spatial-data twins, governed inspection data, and agents driving devices over MCP/MQTT. https://aws.amazon.com/blogs/physical-ai/

**What they'll showcase afterward [inferred]:** measured COOL wins; reusable agentic OpenCV 5 patterns; physical-AI stories with real stakeholders; winners who can carry a 15-minute OpenCV Live segment.

## 5. Likely AWS judges

**Frantz Lohier, PhD** [likely nominee, unverified]
- AWS Senior WW Specialist / BD-GTM leader for AI, robotics and autonomy; formerly Chief Architect at iRobot and CTO at a Tier-1 automotive supplier (FORVIA).
- Co-announced the competition; Satya thanked him for championing it.
- Co-authored the COOL blog (Apr 9, 2026). https://aws.amazon.com/blogs/spatial/category/compute/graviton
- Talks: *Introduction to Designing with AI Agents* (Embedded Vision Summit 2025); COOL (EVS 2026). https://embeddedvisionsummit.com/2025/?p=24163
- **F.R.A.N.T.Z. post (Jun 17, 2026):** composes pre-trained models (MiDaS, YOLO, MediaPipe, DeepLab) with classical OpenCV (ORB, optical flow, MOG2, RANSAC planes, structure-from-motion, point clouds, COLMAP export) to extract scene semantics from monocular video. He frames it as explainable microservices versus opaque vision-language-action monoliths. COOL is the largest cost lever; JEPA-style world models are next. https://aws.amazon.com/blogs/physical-ai/training-world-models-on-scene-semantics-not-pixels/
- His inspection post asks for stable spatial IDs, provenance and decision lineage, including reviewer actions. https://aws.amazon.com/blogs/physical-ai/building-inspection-intelligence-with-aws-spatial-data/
- Uses Codex and Claude himself but insists on understanding the math.

**Other COOL people are OpenCV staff, not AWS:** COOL-blog co-authors Gursimar Singh and Abhishek Gola, and engineer Om Rope.

**Second AWS judge: unknown.** On recent AWS Devpost hackathons, judges were developer advocates, solutions architects and PMs. They rewarded complete products, deliberate architecture and end-to-end demos.

## 6. Past winners and comparable hackathons

| Year | Podium | Notes |
|---|---|---|
| 2020 | Blind-navigation vest; gesture control; parcel dimensioning; forklift perception | Winner interviewed blind users; WSJ coverage; 235 entries. https://opencv.org/opencv-spatial-al-competition-winners-announced/ |
| 2021 | Cortic toolkit ($20k); NICU monitor; EEG wheelchair | Stated aims: social good, accessible edge AI. https://opencv.org/announcing-the-grand-prize-winners-of-opencv-ai-competition-2021/ |
| 2022 Core | Duckweed boat; laser 3D scanner; point-to-read tool | Report + code 80%, video 20%. https://opencv.org/core-opencv/ |
| 2023 | FREISA; exoplanet detection; solo-built guide dog | 117 finals. Judges: Adam [Rodnitzky, from auto-transcript], Katherine Scott, Shiqi Yu, Joseph Nelson. FREISA had no metrics but stated its limits candidly. https://www.hackster.io/b-arol-o/four-legged-robot-ensuring-intelligent-sprinkler-automation-845012 |

**Comparable AWS Devpost hackathons**
- **AWS AI Agent Global Hackathon 2025:** 613 projects, 8 winners; technical execution weighted 50%. https://aws-agent-hackathon.devpost.com/project-gallery
  - 1st place EcoLafaek, described as solo: live dashboard and app, small real usage (50+ reports), candid challenges. https://devpost.com/software/ecolafaek
  - AgentShell used MCP to let an agent control PTZ cameras, with privacy-aware on-demand presence. https://devpost.com/software/agent-shell
- **H0 and Agents for Humans (2026):** judges wanted shippable, complete products rather than demos; live deployment helped. https://h01.devpost.com/ · https://agentsforhumans.devpost.com/

**Why entries lose:** unfinished; crowded templates; computer vision or AWS bolted on; no end-to-end demo; long video; weak docs; unverifiable claims.

## 7. Synthesis

**What they will reward (ranked)**
1. **A real problem shown working in the world**, with perception driving action or field decisions, ideally with a stakeholder — past winners; Phil; Gary; EcoLafaek.
2. **Correct, explainable depth:** OpenCV doing load-bearing work, classical and DNN components composed transparently, beyond what an LLM gives anyone — the exoplanet entry; F.R.A.N.T.Z.; Gary's what/where/why.
3. **Genuine autonomy with a visible closed loop**, plus human override and failure handling; no teleoperation or staged demos.
4. **Spatial/3D or world-model flavor:** SLAM/VPS, calibration, LightGlue/ALIKED/xfeat, Gaussian splats, JEPA-style prediction (Gary, Phil, Frantz, organizer areas).
5. **Honest measurement:** reproducible baselines, a same-instance COOL A/B test, cost per frame, quantitative evaluation and failure cases — a chronic gap in past winners.
6. **Build-on-able docs:** diagrams, a build guide, open code (FREISA; Gary's common substrate).
7. **Sponsor tech that is actually load-bearing:**
   - Graviton price-performance.
   - Agentic OpenCV 5 patterns that can shape OpenCV's roadmap.
   - Developer/optimization agents — Satya's explicit challenge and Gary's own wish; a strong fit for Samuel's trading-systems background.
8. **Presentation:** a ~3:30 video with a working demo early, plus simple illustrations.
9. **Privacy and safety by design.**

**Red flags they'll penalize**
- An LLM wrapper or copycat fine-tune; computer vision that isn't core.
- Teleoperation or staging; synthetic-only evidence; claims with no baseline; misstated human review (grounds for rejection).
- Code the team can't explain.
- An unfinished or over-scoped solo build.
- An undifferentiated assistive, safety, pick-and-place or quality-gate entry.
- COOL or agents added for show.
- Surveillance without safeguards.
- A video over 5 minutes; AWS designed but never deployed; an endpoint that goes down during judging (Oct 27–Nov 9).

*Worth saving to memory:* judges are Bradski and Nelson, with Frantz Lohier (AWS) the likely third; Satya publicly challenged entrants to beat COOL using agents.
