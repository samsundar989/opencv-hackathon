# Responsible use

RiverSight reads public river cameras and drafts flood alerts. A wrong number or an alert sent too early can mislead people about real water, so the system is built to say what it does not know, and to keep a human in charge of anything that leaves it.

## What it is not

- **Not a replacement for USGS gauges or official warnings.** The National Weather Service issues flood warnings; USGS publishes official stage. RiverSight's readings are labelled **provisional**, and the dashboard says so on every site page.
- **Not better than a working gauge.** On the frozen test, the camera never beat a 15-minute-old gauge reading (report §6.4). Its job is to fill outages, show flood state, check the gauge and show where the water is.
- **Not reliable above its calibrated range.** A flood higher than anything in a camera's calibration history is read as roughly the calibrated maximum (report §6.6). Flood state still fires, and the live system should treat readings at the edge of the range as "at least this high".
- **Not for night.** Night and IR frames are not scored. The site shows "night" instead of a number.
- **Not for ungauged cameras.** Calibration needs the co-located gauge's history.

## Human control

- **Alerts and tickets need a person.** The agent may draft an alert (`DRAFT_ALERT`) or open a ticket (`OPEN_TICKET`), but both wait as pending approvals until a human approves them on the dashboard or through the e-mail link. Nothing goes to the public automatically.
- **Autonomous actions are reversible and logged:** switching to a banked reference view, quarantining a camera, sampling more often, marking a reading provisional. Each is logged with its evidence, tool trace, tokens and cost (`live/agent/YYYY-MM-DD.jsonl`).
- **Kill switch:** setting `live/agent/ENABLED` to false in S3 turns the agent into a no-op. A deterministic rules policy takes over when Bedrock fails or the daily token cap is hit.
- **The approval token** reaches the operator by SNS e-mail and is never stored in the repository.

## Privacy

- Every frame is passed through YuNet face detection (`cv2.FaceDetectorYN`) and faces are blurred before the frame becomes an overlay, a dashboard image or a demo asset. The blur fails closed: if the model file is missing, the frame is not published.
- **No images go to the LLM.** The agent receives numbers and one-line summaries from OpenCV tools (registration score, quality metrics, stage ± σ, gauge readings), never pixels.
- No personal data is collected. The approval page has no accounts; one operator holds the token.

## Data and licensing

- Images: USGS HIVIS / NIMS, public domain (some cameras are run with cooperators; credit "USGS HIVIS" on every derived image).
- Stage: USGS NWIS instantaneous values, public domain. The NWS forecast comes from the public NWPS API.
- **We do not redistribute raw frames.** The repository holds derived, face-blurred overlays for illustration. Raw frames stay in a local cache and the project's private S3 bucket. A public benchmark would be a manifest of image URLs, labels and splits.
- USGS services are queried gently: at most four concurrent requests, exponential backoff, everything cached, an API key for the OGC service.

## Known failure modes

Each has a concrete case in `results/failures/` (being assembled) and in report §6–7:
- **Camera moved or re-aimed** → registration score drops → `VIEW_CHANGE` → the agent re-anchors or quarantines.
- **Fog, rain on the lens, glare, spider webs** → quality metrics flag `LOW_QUALITY`; the agent checks before trusting the stage.
- **Seasonal change** (vegetation, sun angle, sediment) → slow drift; the live models are refit periodically, and the frozen numbers are never mixed with live ones.
- **Floods above the calibrated range** → the reading saturates; flood state still fires.
- **Tidal or managed flows** (First Mallard, Langham reservoir outflow) → the scene can change without the stage changing, or the reverse.
- **Gauge errors** → camera–gauge disagreement opens a "gauge suspect" ticket for a human, never an automatic correction.

## Cost and security

- AWS spend is capped at $100 for the competition (D-0004): an AWS Budget with alerts and an automatic stop of EC2, created before any instance was launched.
- The LLM is only called for flagged readings, with at most a fixed number of tool calls per event and a daily token cap enforced in code.
- The worker uses IMDSv2, no SSH, and a least-privilege instance role. The benchmark instance needs no role at all (presigned URLs) and terminates itself.
- No secrets in the repository; a full-history secrets scan runs before the repository is made public.
