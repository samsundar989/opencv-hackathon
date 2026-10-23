# Prior art, and what RiverSight claims

Camera-based water-level measurement is established. We build on it; we do not claim to have invented it. Research notes with full links: `docs/research/prior-art.md` (Oct 13) and `docs/research/2026-10-22_rivals.md` (Oct 22). Figures quoted below are the authors' own, not reproduced by us.

## Systems that need a survey, a target or a plate

- **Commercial:** OTT HydroSight and Tenevia CamLevel read the waterline on their own cameras after a technician surveys reference points and the cross-section. Hydro-STIV (Japan) does the same for flow and level.
- **Research with surveyed geometry:** Blanch, Grundmann, Hedel & Eltner (HESS 2026) combine water segmentation, ground-control-point detection and a 3-D site model for centimetre accuracy at 4 sites. Erfani et al. ("Eye of Horus", HESS 2023) use a phone LiDAR cloud and surveyed markers. Vandaele, Dance & Ojha (HESS 2021) use surveyed landmarks.
- **Installed targets:** the GRIME lab's octagon and bow-tie targets (GRIME2); USGS time-lapse "camera-stage" from installed PVC pipes at three Wisconsin gauges (Johnson, Reneau & Komiskey 2025).
- **Staff-plate readers:** a 2026 MLIT pilot in Japan, and, in this competition, **StageSight**, which reads the red-marked staff plate on the USGS NIMS camera at Hancock NY (one of our 20 sites) with OpenCV 5 and needs no gauge history. We compare against it in report §6.6.

All of these measure stages they have never seen before, which RiverSight cannot (report §6.6). All need something physical or surveyed at the site, which RiverSight does not.

## Survey-free systems

- **Regression on USGS webcams:** Xu & Wang (Hydrology 2025) on one HIVIS camera; Windheuser et al. (ESS 2023) on two; Vanden Boomen (thesis 2021) on three. Per-site black-box CNNs, one to three sites, no held-out sites.
- **Fleet-scale but not metric:** Vandaele et al. (Env. Data Sci. 2023) regress a standardised (z-scored) level from 95 UK cameras using nearby gauges.
- **Chapman et al.** (HESS preprint 2020; AGU 2024) learn stage from image features and water segmentation at one Platte River site and on HIVIS imagery.

## Programmes on HIVIS itself

- **USGS RISE:** a public-domain image + stage training set from 20 USGS stations (Reneau & Johnson 2023).
- **Stevens Institute / CIROH** (USGS–NOAA grant, from 2023): operational HIVIS computer vision (segmentation, ice and obstruction detection, velocimetry), not yet published for stage.
- **USGS NWDTW 2026:** an internal comparison of Tenevia/Noema, EfficientNet regression and staff-plate segmentation across USGS camera sites.
- **GRIME-AI** (open source) downloads HIVIS, PhenoCam and NEON imagery with stage and segments it, but does not output stage.

## What RiverSight adds, narrowly and truthfully

- **Fleet-scale, plate-free and survey-free.** One method calibrates every camera from its co-located gauge's history; nothing is installed or surveyed. 20 cameras run live.
- **An explicit, inspectable scene model**, not a black-box CNN: a per-block flood-height map says which patch floods at which stage, and doubles as the "what's under water at stage X" visual.
- **A frozen held-out benchmark:** pre-registered criteria, constants hashed before the test read, the test read once, like-for-like baselines (persistence, last-known value, constant) and bootstrap CIs (report §6).
- **Camera QA and an agent with human approval:** view change, lens and gauge-disagreement handling, provisional gap-fill, alerts drafted for a human.
- **OpenCV 5 on Graviton with COOL,** benchmarked against stock OpenCV.

**Our claim:** to our knowledge, RiverSight is the first open, fleet-scale, plate-free and survey-free camera stage system, with a frozen held-out benchmark, a live endpoint and agentic QA.

**We do not claim:** the first camera water-level system; the first stage estimate from a HIVIS camera; the first HIVIS image–stage dataset (RISE exists); centimetre accuracy; or transfer to ungauged cameras.
