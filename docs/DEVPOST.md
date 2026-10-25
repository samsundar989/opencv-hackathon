# Devpost submission text (draft for Cowork to edit)

Every number below is traced by `python scripts/check_report_numbers.py` to a committed results file. Field names follow the Devpost project form.

---

## Project name
RiverSight

## Elevator pitch (≤ 200 characters)
Public USGS river webcams read the water level, show what's under water, and flag when the camera or the gauge can't be trusted. OpenCV 5 on Graviton, with a human-approved AI agent.

## Inspiration
Stream gauges go dark, drift, ice up and get washed out, often when floods hit. Over the past year, 531 of the 875 gauges behind USGS's public river cameras had at least one outage of six hours or more. Right beside many of them is a USGS webcam that nobody reads as an instrument, because pixels are not feet. Responders also struggle to picture what "12.3 ft" means on the ground. We wanted the camera to answer both questions: how high is the water, and where is it?

## What it does
- **Reads the river stage from the camera,** with no staff plate and no survey. Each camera learns from its own gauge's history which patches of the scene go under water at which stage (a *flood-height map*), and turns a new frame into stage ± σ.
- **Shows the flood in the picture.** A slider on every site page draws what is under water at any stage, only where water can physically connect to the river.
- **Fills gauge outages.** On frozen test days scored once, the camera beat the gauge's last known value at 15/20 sites after a 72-hour outage and at 18/20 after 7 days. The fused RiverSight stage (last gauge value, updated by the camera) halves the error during multi-day outages when the river moves: 0.55 vs 1.14 ft at 72 h.
- **Checks both instruments.** It detects moved, fogged or re-aimed cameras through OpenCV registration and image-quality signals, and catches gauges that disagree with a confident camera.
- **Replay a flood:** every featured site can replay a real past flood frame by frame (camera, gauge, overlay, agent decisions), so you can see it work even when rivers are calm.
- **River Steward agent.** OpenCV-grounded rules act on flagged readings: re-anchor, quarantine, mark gap-fill provisional, densify sampling. Claude on Amazon Bedrock advises: it ranks the fleet, gives a second opinion and drafts alerts. A human approves anything that leaves the system.
- **Runs live** on AWS Graviton5 with OpenCV's COOL build, every 15 minutes, for 20 frozen-test cameras plus newly onboarded ones.

## How we built it
- **OpenCV 5 does the heavy lifting.** ALIKED + LightGlueMatcher (new in 5.0, on the new DNN engine) and USAC_MAGSAC register each frame to its reference: 95.7 % of daylight frames, against 39.6 % for ORB alone. `warpPerspective`, `resize`, Lab `cvtColor` and `Sobel` build per-block features. `connectedComponentsWithStats` keeps the drawn flood connected to the river. `FaceDetectorYN` blurs faces before any frame is published. `imwriteanimation` writes the event GIFs. A DINOv2 candidate model also runs entirely in `cv2.dnn`.
- **Scene model:** flood-height map + kernel ridge + causal Kalman, one global setting chosen by forward-chaining CV inside the history, hashed, then scored once on held-out days.
- **AWS (us-east-2):** EC2 m9g.large (Graviton5) from the COOL AMI, S3 + CloudFront, a Lambda Function URL for approvals, SNS, Amazon Bedrock (Converse tool use), CloudWatch, and an AWS Budget that stops the instance before the $100 cap. All of it is CDK.
- **Honest evaluation:** pre-registered criteria, a frozen setting, test days read once, bootstrap CIs, a prospective live score, a failure gallery, and a script that refuses to publish any number not found in a committed results file.

## Challenges we ran into
- **The camera never beats a 15-minute-old gauge reading** (0/20 sites). We rebuilt the product claim around what the data supports: gap-fill, flood state and QA, not replacement.
- **Floods bigger than anything in the calibration history.** In a head-to-head at Hancock NY, with the flood left out of calibration, our model read 4.32 ft RMSE and saturated near its calibrated ceiling. Flood state was still right. We report it, flag those readings "≥ X ft", and trust the gauge.
- **Cameras move:** 8 of 20 have history periods taken from a different view.
- **Seasons drift:** year-long CV error (0.38 ft) is about twice the test-day error (0.182 ft).
- **An LLM should not drive alone.** On 98 frozen episodes, OpenCV-grounded rules scored 93.9 %, Claude Sonnet 4.6 71.4 % and Claude Haiku 4.5 58.8 %. So we set the autonomy split by that measurement.

## Accomplishments that we're proud of
- **The frozen test passed:** 14/20 sites within 0.25 ft or 10 % of range (bootstrap interval 12–16); median MAE 0.182 ft (95 % CI 0.148–0.22). Flood-state balanced accuracy 0.93 vs 0.75 for a 24-hour-stale gauge.
- **Self-onboarding:** 30 of 40 new cameras qualified with one command each and the frozen setting, at about $0.055 of compute per camera.
- **COOL, measured honestly:** bit-identical outputs, 1.16–1.21× faster on the classical registration path, flat end to end because the learned matcher dominates. One m9g.large covers all ~880 gauged HIVIS cameras at a 15-minute cadence for about $0.06 per camera-month.
- **A DINOv2-in-OpenCV candidate model** cut year-long CV error from 0.380 to 0.252 ft and improved 19 of 20 sites. In a pre-registered live shadow it read 0.084 vs 0.183 ft on 249 paired readings, and it was promoted to the live model on Oct 24 under those pre-registered criteria.
- **Autonomy chosen by measurement:** the hybrid (rules act, Claude advises, a human approves) scored 94.6 % on 98 frozen episodes. We also logged and fixed a real false alert that a human approved at a tidal site.
- **Reproducible:** a fresh clone re-derives every reported number and verifies the frozen hashes in about 80 s.

## What we learned
Measure before you claim. Several of our first stories didn't survive contact with the data: one camera "learned the sun, not the water", the seasonal curve wasn't clean, and the plate reader beat us on its own camera. Saying so made the product sharper.

## What's next
See `docs/ROADMAP.md`: every gauged HIVIS camera, a public API, night/IR flood state, per-site recalibration after each flood, and partnerships with USGS water science centers, NWS forecast offices and county flood managers.

## Built with
OpenCV 5 (ALIKED, LightGlue, USAC_MAGSAC, DNN engine, FaceDetectorYN) · OpenCV COOL on AWS Graviton5 · Python · NumPy · AWS (EC2, S3, CloudFront, Lambda, SNS, Bedrock, CloudWatch, Budgets, CDK) · Claude on Amazon Bedrock · USGS HIVIS / NIMS · USGS NWIS · NWS NWPS · Leaflet · Chart.js

## Links
- Live: https://d2aes2r6og8aap.cloudfront.net. Start at `/judge`, then Salt Creek → Replay a flood.
- Repository: _(link at submission)_
- Technical report: `report/REPORT.pdf`
- Video: _(link at submission)_
