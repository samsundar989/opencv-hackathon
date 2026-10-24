# RiverSight roadmap: from competition entry to a service people rely on

RiverSight already runs live on a Graviton worker, onboards a new camera with one command, and reports honestly where it fails. This is the path from there to a tool that a USGS water science center, an NWS forecast office or a county flood manager would use every day. Figures come from committed results (`results/`). Each phase lists what it costs and how we would know it worked.

## Phase 1 (weeks 1–4): cover every gauged HIVIS camera

- **Onboard the whole gauged fleet** with the W5 pipeline (`scripts/onboard_site.py`, frozen setting, automatic tiering). At the measured cost per camera that is about $48 of compute and 105 GB of frames for all ~880 gauged cameras (`results/onboarding/README.md`). Only tier A/B cameras are served; tier C stays in a "needs attention" list.
- **Serve them all from one instance.** One m9g.large covers ~880 cameras at a 15-minute cadence for about $0.06 per camera-month (`docs/COOL_BENCHMARK.md`).
- **Nightly incremental fetch and weekly refit,** so each flood the gauge records extends the camera's calibrated range: the lesson from the Hancock flood (report §6.6). Every refit is scored in shadow before it serves, as model v2 was (D-0010).
- **Success measure:** prospective live accuracy per camera, published daily. A camera that drifts below its tier is demoted automatically.

## Phase 2 (months 1–3): a product people can consume

- **Fused "RiverSight stage"** as the headline output: the gauge when it is fresh, a camera gap-fill with growing σ when it is not, and a lower bound above the calibrated range, each with a provenance label.
- **Public API and feeds:** per-camera JSON (latest and history), an Atom feed of flood-state changes and approved alerts, documented schemas. Static files behind CloudFront, so it scales at negligible cost.
- **Fleet health for operators:** a daily report of cameras offline, re-aimed, fogged, stuck in IR, or disagreeing with their gauge. Every ticket is drafted with evidence images and sent only after a human approves.
- **"Add a camera"** self-service: any gauged HIVIS camera can be requested; an operator approves; the pipeline runs.
- **Success measure:** gauge outages bridged in real time, with error against the backfilled record once USGS publishes it.

## Phase 3 (months 3–6): beyond daylight and beyond gauges

- **Night/IR flood state:** many HIVIS cameras switch to infrared at night. A per-site IR classifier for normal / elevated / flood, released only where forward-chaining CV beats persistence.
- **Model v2 in production** where it wins: DINOv2 features in `cv2.dnn` cut year-long CV error from 0.380 to 0.252 ft (`results/v2/`). Serve it per site, behind a shadow comparison.
- **Ungauged cameras (research):** calibrate from a handful of staff-plate reads or a neighbouring gauge instead of a full gauge history. This is the one capability that would extend the method to cameras with no gauge, and it needs its own held-out benchmark before any claim.
- **An open benchmark:** a public manifest of image URLs, labels and splits (no redistributed frames), so others can compare methods on held-out sites and time.

## Partnerships

- **USGS HIVIS team and water science centers:** camera QA (moved, fogged, offline) and gauge-suspect tickets, so field visits are prioritised. A note to the HIVIS team is drafted (`docs/OUTREACH_DRAFT.md`) for Samuel to send from his own email.
- **NWS forecast offices:** flood state where the gauge is out, and the forecast crest drawn into today's picture.
- **County flood managers:** low-water-crossing decisions with a picture, never as a replacement for official warnings.

## What stays true

- RiverSight supplements gauges and official warnings. It never replaces them.
- Alerts and tickets always wait for a human.
- No images go to an LLM; faces are blurred before anything is published.
- Every number we publish traces to a committed result produced by committed code.
