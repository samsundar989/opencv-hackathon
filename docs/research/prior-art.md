# F. Prior art: "Does anything already do what RiverSight does?" (2026-10-13)

**Short answer.** Camera-based water-level measurement is mature (commercial products, dozens of papers, sub-cm accuracy with surveyed references). Direct "USGS webcam → gauge height" CNN regression has been published at 1–3 sites at least four times. Stevens/CIROH ($870k) and USGS itself are building HIVIS-scale stage-from-imagery systems, and USGS already released a CC0, 20-station image+stage training dataset (RISE). **Nobody we found has published metric stage for the whole public HIVIS fleet with zero on-site survey, a held-out-site benchmark with baselines, a live derived-stage endpoint, or agentic QA.** That is the honest gap. [unverified] marks inference.

## 1. Commercial products

| Product | What it does | Per-site calibration | Cameras / scale | Pricing |
|---|---|---|---|---|
| **OTT HydroSight Level / Flow** (OTT HydroMet) | Waterline on a physical staff gauge (+ "virtual staff gauge" overlay); LSPIV-style discharge. <1 cm claimed. | **Mandatory**, by certified OTT technicians: topographic survey of reference points, bathymetric cross-section; staff gauge ≥1 m visible. Bank features used to auto-correct camera motion. | Edge app on Axis cameras (own station hardware) | Perpetual per-camera licence, no public price. [Tech desc.](https://cdn.hach.com/1XMCM0ZF/at/7n8sp6r4t8sgqgnfm2625s3/OTT_HydroSight_Technical_Description_en.pdf) |
| **Tenevia CamLevel / CamFlow** (France) | Water level; LSPIV discharge. Edge apps on Axis cameras, output "augmented images for remote verification". | Not public on site; survey of in-view reference points required [unverified]. | Own IP-camera installs; deployment count not public. [Axis partner page](https://www.axis.com/en-us/partner-finder/tenevia), [tenevia.com](https://www.tenevia.com/en/) | Not public |
| **Noema Flooding Detector** (DSR Corp.) | Counts water pixels / water-area change for flood alerts on i-PRO cameras. No metric calibration described. | None described | i-PRO edge cameras | Licence by email. [i-PRO page](https://i-pro.com/products_and_solutions/eu-en/node/119556) |
| **Hydro-STIV** (Hydro Technology Inst., Japan) | STIV discharge; water level by detecting water edge on gauges/piers/walls; DL for noise. | Survey/scale from two points; details not public | Own/drone/IR cameras; used in AU, CA, NZ, US. [site](https://hydrosoken.co.jp/en/hydrostiv/) | Trial + quote |
| **Photrack DischargeApp** | Smartphone SSIV discharge; water level entered by user. | Marked cross-section, measured distances (<1 h) | Smartphones | Regional plans. [FAQ](https://discharge.ch/faq.html) |
| **Divirod** (GNSS reflectometry, [patent](https://patents.justia.com/patent/11719732)), **Hohonu** (low-cost sensors, 230+ sites, [HPR](https://www.hawaiipublicradio.org/the-conversation/2026-09-02/this-hawaii-based-tech-helps-the-country-fight-flash-floods-faster)), **FloodNet NYC** (ultrasonic, [paper](https://repository.library.noaa.gov/view/noaa/68675)) | **Not camera-based** | n/a | Own sensors | — |
| **ClearObject Vision AI** | Roadway flood *presence* on traffic cams, no depth. [site](https://www.clearobject.com/flood-detection-clearflood-vision-ai-blog/) | — | Existing cams | — |
| **Japan MLIT pilot (Takuwa Co.)** | AI reads staff gauge from high-sensitivity camera; 3 mm vs visual, within ±1 cm std; 1 camera, 14-week demo, not operational. [MLIT PDF](https://www.ktr.mlit.go.jp/ktr_content/content/000934127.pdf) | Staff gauge in view, site-trained | 1 | — |
| Vaisala, Green Stream, K-water, UK/AU council "AI flood cams" | Nothing camera-stage-specific found in a bounded search [unverified]. | | | |

**Pattern:** every commercial system needs its own hardware plus a technician-installed surveyed reference. None ingests existing public webcams at scale.

## 2. Government / research programs on HIVIS specifically

- **Stevens Institute (Temimi & Liu), $870,614 USGS/NOAA-CIROH grant, started 2023**: "Leveraging HIVIS for Operational Monitoring of Streamflow using Computer Vision." Plans: pre-trained DL segmentation adapted to HIVIS, obstruction (ice/debris) detection and auto-correction, LSPIV velocity, discharge; three software packages "delivered to USGS for testing and potential operational deployment"; later citizen-science images. **Status:** CIROH page (updated Jul 2025) still future-tense; no stage accuracy, no stage code released. Published spin-offs: **RIce-Net** river-ice classification/segmentation on one HIVIS site (CC BY, [HydroShare](https://hydroshare.org/resource/ff4e9c4e87ef4d7d923efe77f5ed2b83/), [USGS pub](https://pubs.usgs.gov/publication/70265885)) and **HIVIS Hydro-Haze** dehazing dataset, 6,587 images, 9 Alaska stations ([HydroShare](https://www.hydroshare.org/resource/2aca7bf88a944b86af4cd4c4b01bed71/)). Sources: [Stevens news](https://www.stevens.edu/news/temimi-and-liu-awarded-usd870-614-united-states-geological-survey-grant-to), [CIROH](https://ciroh.ua.edu/?p=3960). **This is the closest institutional competitor; expect a paper any time.**
- **USGS internal (RISE = River Imagery Sensing):** "Imagery training dataset for the RISE application" (Reneau & Johnson, Dec 2023, **CC0**): time-lapse images from **20 USGS stations**, Dec 2016–Nov 2022, ~126 GB, with per-station CSVs of stage/gage height/discharge/weather; trail cams, webcams and a custom RISE camera; purpose "develop AI models that monitor water surface elevation" ([USGS](https://www.usgs.gov/data/imagery-training-dataset-river-imagery-sensing-rise-application), [ScienceBase](https://sciencebase.gov/catalog/item/62547935d34e21f8276f425d)). Also Johnson, Reneau & Komiskey 2025, *J. Hydrol. X*: "camera-stage" from **installed PVC pipes / a wall** at 3 Wisconsin gauges, WY2020; 38–92 % of images usable, 79–99 % of those within ±0.10 ft; R code + images released CC0 ([USGS](https://www.usgs.gov/data/time-lapse-imagery-image-derived-water-level-data-and-model-archive-three-usgs-streamgages)). USGS "1,000 cameras and counting" (May 2026) mentions ML "for detecting river ice and estimating hydrologic variables" ([USGS](https://www.usgs.gov/mission-areas/water-resources/news/1000-cameras-and-counting)); HIVIS is now >1,000 cameras, not ~900. Jack Eggleston (USGS HRSB) talk lists RISE as "measures water levels from imagery" ([CIROH forum](https://ciroh.ua.edu/water-observing-technology-forum/water-observing-technology-forum-speakers/)).
- **NWDTW 2026 (Jul 22) USGS talk** evaluates, "across a network of USGS monitoring sites with fixed-mount cameras": (1) commercial optical gauging software **Tenevia and Noema**, (2) **EfficientNet-B0 regression** of gage height from the full scene, (3) **staff-plate segmentation** → air-water interface → stage. Speaker and results not posted ([sched](https://nwdtw2026.sched.com/event/2NP0T)). Same workshop demoed NIMS API + **pyNIMS** Python client ([sched](https://nwdtw2026.sched.com/event/2NP0N)). **USGS is therefore internally benchmarking exactly our three baseline families.**
- **UNL GRIME Lab (Gilmore; Chapman; Stranzl):** GRIME2 reads stage with an **installed octagon/bow-tie target** (KOLA: 26 months, 52,570 images, 90 % within 3 cm; [HydroShare](https://www.hydroshare.org/resource/a152931d41c44de2935cc02ced44a5c2/)). **GRIME-AI** (Apache-2.0, [GitHub](https://github.com/JohnStranzl/GRIME-AI)) downloads **NEON/PhenoCam/USGS HIVIS** imagery paired with stage/discharge, runs SAM2/SegFormer-LoRA/YOLOv11, color indices, model fine-tuning; **does not output stage**. Chapman, AGU24 H13C-1053: "Water Segmentation for Water Level Determination using USGS HIVIS Imagery" (abstract not retrievable; [AGU](https://agu.confex.com/agu/agu24/meetingapp.cgi/Paper/1680857)). Chapman et al. 2020 HESS-preprint: image features → ML → stage at one Platte site, RMSE 6–23 cm ([HESS](https://hess.copernicus.org/preprints/hess-2020-575/hess-2020-575.pdf)).
- **CIROH / Utah State (Sierra Young, 2023–May 2026)**: MobileSAM water level + velocimetry on 2–3 own cameras, AWS serverless + Jetson ([CIROH](https://ciroh.ua.edu/?p=1525)). **USACE/NOAA/NWS:** nothing camera-stage-specific found [unverified]; SECOORA WebCOOS does coastal webcam flood algorithms.

## 3. Academic state of the art

| Work | Method | Accuracy | Calibration | Sites | Code/data |
|---|---|---|---|---|---|
| **Blanch, Grundmann, Hedel, Eltner, HESS 2026** ([link](https://hess.copernicus.org/articles/30/797/2026/)) | UPerNet-ResNeXt50 water seg + R-CNN GCP keypoints + image-to-3D-model projection; 2.5 yr, ~218k images | MAE 1.3–2.7 cm | RTK-GNSS GCPs, SfM 3D model, surveyed cross-sections; GCP damage is main maintenance issue | 4 (Saxony), own Axis cams | not stated |
| Zamboni…Eltner, IJRS 2025 ([link](https://fis.tu-dresden.de/portal/en/publications/do-we-need-to-label-large-datasets-for-river-water-segmentation-benchmark-and-stage-estimation-with-minimum-to-nonlabeled-image-time-series(de07e6a1-424f-4b6c-8050-853dbde9d5ca).html)); EGU25 stereo (DUSt3R/MASt3R) to drop GCPs | STCN / SAM / SAM+GroundingDINO, near-zero labels | qualitative | as above; stereo needs baseline only | 3 cams + UAV | not stated |
| **Vandaele, Dance, Ojha, HESS 2021** ([link](https://hess.copernicus.org/articles/25/4435/2021/)) | DeepLab/UperNet transfer seg; landmark-based level or SOFI index | >91 % landmark acc.; r>0.94 vs gauges | surveyed landmarks (LBWLE) | 4 Farson cams (UK) | not stated |
| **Vandaele et al., Env. Data Sci. 2023** ([link](https://www.cambridge.org/core/journals/environmental-data-science/article/calibrated-riverlevel-estimation-from-river-cameras-using-convolutional-neural-networks/912B6F25D567B59C38C6D76185829F76)) | ResNet-50 regresses **z-scored** level using gauges ≤50 km; 95 cams, ~327k images | standardized units only, no metres | **none** | 95 (UK/IE, Farson, licensed) | imagery licence-restricted |
| **Xu & Wang, Hydrology 2025** ([link](https://www.mdpi.com/2306-5338/12/4/65)) | CNN3/VGG16/ResNet50 regress gage height from **one HIVIS camera** (Hermann, MO), 17,446 imgs | RMSE ≈12–26 cm; test overlaps train period | none (augmentation only) | 1 | no code |
| Vanden Boomen, UWM thesis 2021 ([link](https://minds.wisc.edu/items/6b009d43-68ba-4caa-b46c-bb60b91473eb)); Buscombe CSDMS 2019 | transfer-learned CNN regression on USGS webcams | qualitative | none (per-site model) | 3 | none |
| Windheuser et al., ESS 2023 ([link](https://par.nsf.gov/servlets/purl/10402496)) | U-Net seg → CNN regression, USGS webcams; LSTM forecast | MAE 0.0035–0.065 ft (~300 imgs) | none | 2 (GA) | GitHub + Kaggle images |
| **Erfani…Goharian, "Eye of Horus", HESS 2023** ([link](https://hess.copernicus.org/articles/27/4135/2023/)) | SegFormer seg + iPhone LiDAR cloud + KNN to waterline | RMSE ~1.6–6.5 cm | checkerboard + 13 ArUco surveyed with total station | 1 (SC) | Zenodo code |
| Jafari…Li, C&G 2021 ([pdf](https://www.ece.lsu.edu/xinli/WaterNet/WaterNet20ComputersGeosciences.pdf)) | FCN seg of water + reference object (pier/pole) | RMSE 0.4–2 cm | known reference length / surveyed pier | 2 + Harvey video | GitHub |
| **Sun, arXiv 2605.14645 (May 2026)** ([link](https://www.alphaxiv.org/abs/2605.14645.md)) | SAM2/RITM prompts, **LightGlue drift correction**, "virtual staff gauge" by perspective warp of 4 gauge corners or surveyed points, STIV flow | ~5 cm with gauge, ~10 cm without | 4 corner points or RTK survey | n/s | "will be available" |
| Hohai Univ. 2026 ([link](https://jour.hhu.edu.cn/hhdxxbzren/article/abstract/20260303)) | PSPNet + virtual gauge from **surveyed cross-section**, no GCPs | <2 cm | cross-section survey | n/s | n/s |
| Bharti 2022 (HED edges, pier template); Vigneswaran arXiv 2512.23454 (YOLO gauge + GPT-4o, MAE 5.4 cm); Noto/Tauro 2022 stage-cam targets | edge/gauge-reading variants | ~cm–5 cm | reference object or gauge in view | 1 each | partial |
| LSPIV tools: **pyorc/OpenRiverCam** ([EGU21](https://meetingorganizer.copernicus.org/EGU21/EGU21-5880.html)), RIVeR, Fudaa-LSPIV | discharge; level from staff gauge | — | GCPs + bathymetry | — | open |

**Reading:** sub-3 cm needs surveyed geometry. Survey-free approaches so far are black-box regressors (12–26 cm, 1–3 sites, no held-out sites) or non-metric indices (Vandaele 2023). No published method fits an explicit projective waterline→stage model from gauge history alone.

## 4. Open-source repos / datasets

- Image+stage data: **USGS RISE** (20 stations, CC0); Johnson 2025 WI release (CC0); Windheuser Kaggle set; Reading/Farson Tewkesbury 2012 (licence-restricted imagery); CrowdHydrology 141 gauge photos ([HydroShare](https://hydroshare.org/resource/79b25776e1624176ab781019a49f25ec/)); GRIME PEP2026 HIVIS samples (CC BY). Segmentation-only: ATLANTIS, Liang 2020, Pally 2022, RIce-Net, Hydro-Haze.
- Access tooling without stage: **pyNIMS** (USGS, Jun 2026), R **flowcam** ([manual](https://connorb.r-universe.dev/flowcam/doc/manual.html)), GRIME-AI downloader. **No repo found that outputs metric stage for arbitrary HIVIS cameras.**

## 5. OpenCV AI Competition 2026 entries

Devpost gallery was not fetchable (client error); searches surfaced no water-level entries beyond the four already known (AquaTrace, FloodLens, CurvFlood, Streamproof — not re-verified). Treat the gallery as **unchecked**; re-check manually before submission.

## 6. Synthesis

### (a) What exists vs what RiverSight adds

| Capability | Exists today | RiverSight |
|---|---|---|
| Camera → metric stage | Yes: OTT, Tenevia, Eltner, Horus, Sun (all need survey/gauge/target) | Yes, **zero on-site survey** |
| Stage from public USGS webcams | Yes, 1–3 sites, black-box CNN (Xu & Wang; Windheuser; Vanden Boomen) | Fleet-scale (~1,000 cams), physics-constrained 1-D projective model per transect |
| Calibration from gauge history | Vandaele 2023 (z-score only); CNN regressors (implicit) | Explicit cross-ratio fit → metric, interpretable, few parameters, transferable through gauge outages |
| Camera-drift handling | OTT bank features; Chapman weir search; Sun LightGlue | ALIKED+LightGlue+MAGSAC re-registration + agent re-anchoring |
| Obstruction/QA | Stevens (ice), USGS image-suitability (manual) | Agentic quarantine, suspect-gauge flags |
| Forecast overlay + drafted alert | none found | New |
| Public HIVIS image–stage dataset | **USGS RISE (20 stations, CC0)**; Stevens ice/haze sets | Benchmark with held-out sites/time, baselines, ablations, failure gallery |
| Live national derived-stage endpoint | none public (Stevens → USGS pending; USGS RISE internal) | New |
| OpenCV 5 DNN/ALIKED/LightGlue + Graviton/COOL | none | New (engineering, not science) |

### (b) Innovation (20 pts) — honest forecast

A knowledgeable judge knows camera stage is well-trodden (OTT/Tenevia ship it; Eltner gets 1–3 cm). "Thoughtful use" credit comes from *how* we remove the survey: a geometric model fitted from free ground truth, fleet-wide, with explicit QA. Expect **13–16/20** if framed as "turning an existing public sensor network into a second, redundant instrument" with citations; **≤10/20** if we claim "first camera water-level system" — USGS/CIROH-aware reviewers would spot it. The objection a judge will raise: *the gauge already exists where the camera is*; value must be argued as redundancy during gauge failure/ice/flood damage, independent QA of gauges, and future transfer to ungauged DOT/traffic cameras — which gauge-history calibration **cannot** do without a survey. Say so.

### (c) Strongest truthful novelty claim + mandatory prior-art sentence

**Claim:** "RiverSight is, to our knowledge, the first open system that converts an entire public river-webcam network (USGS HIVIS, >1,000 cameras) into metric water-level instruments with no on-site survey, staff plate or target — each camera self-calibrates a per-transect projective waterline-to-stage model from its co-located gauge's own history — and the first open held-out-site benchmark and live endpoint for image-derived stage on HIVIS."

**Prior-art sentence (verbatim in report):** "Camera-based stage measurement is established: commercial systems (OTT HydroSight, Tenevia CamLevel) and research pipelines (Blanch & Eltner 2026, 1–3 cm MAE; Erfani 2023) achieve centimetre accuracy using surveyed references, and single-site CNN regression on USGS webcams has been reported (Xu & Wang 2025, 12–26 cm RMSE; Windheuser 2023; Vanden Boomen 2021). USGS released a 20-station image–stage training set (RISE, 2023) and, with Stevens Institute (CIROH), is developing operational HIVIS computer vision; a USGS 2026 study compares Tenevia/Noema, EfficientNet regression and staff-plate segmentation. RiverSight builds on this work and differs in scope (fleet-wide), calibration (survey-free, from gauge history), evaluation (held-out sites) and openness."

### (d) Red flags

1. **USGS RISE dataset already exists (CC0, 20 stations, image+stage).** Do not claim "first HIVIS image–stage dataset"; claim first *benchmark* (splits, baselines, metrics) and include RISE sites for comparability.
2. **Stevens/CIROH and USGS NWDTW results may publish before Oct 26**, including EfficientNet and staff-plate baselines on many sites. Monitor and cite.
3. **Imagery licence:** HIVIS docs say content is "mostly public domain but may contain copyrighted material"; some cameras are cooperator-owned [unverified]. Verify per-camera ownership before redistributing a dataset; NIMS API appears to need an API key (flowcam `set_usgs_api_key`) — check ToS/rate limits.
4. **Patents:** "Camera-based liquid stage measurement" (prov. 2020) claims phone-pose + terrain-model geometry, not our method; OTT/Tenevia may hold EU patents on virtual-gauge calibration [unverified]. Low risk for an open research entry; avoid "virtual staff gauge" as a product name.
5. **Baseline honesty:** Xu & Wang's split leaks time; our held-out-site/time protocol is a differentiator.
