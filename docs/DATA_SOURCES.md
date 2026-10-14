# Data sources (verified 2026-10-13)

All endpoints below were exercised from a browser on Oct 10 and Oct 13, 2026. Keep this file as the single source of truth for URLs and shapes; update it when something changes.

## 1. USGS NIMS / HIVIS cameras (images)
- **List cameras:** `GET https://api.waterdata.usgs.gov/nims/v0/cameras` → JSON array (1,369 cameras on Oct 13). No key required.
  Fields: `camId`, `nwisId` (USGS site number, 8–15 digits; may be empty), `camName`, `camDesc`, `lat`, `lng` (strings), `stateAbrv`, `tz`, `createdDate`, `modifiedDate`, `newestImageDT`, `TL_enabled`, `TL_lastGeneratedDT`, `TL_lastImageUsedDT`, `hideCam`, `overlayDir`, `thumbDir`, `smallDir`, `tlDir`, `ingest`, `locus`.
  Optional query: `camId=`, `siteId=`, `returnFields=`.
  Oct 13 counts: 917 cameras with an image in the last 48 h; **880 of those have an `nwisId` and `hideCam == false`**; 833 are older than 90 days; 657 predate Jun 2025; Texas has 47 active gauged cameras.
- **List images for a camera:** `GET https://api.waterdata.usgs.gov/nims/v0/listFiles?camId=<camId>&after=<ISO>&before=<ISO>&limit=<n>&recent=true|false`
  → JSON array of filenames, e.g. `TX_Guadalupe_Rv_at_Comfort___2026-10-10T11-41-21Z.jpg` (timestamp is UTC, `HH-MM-SSZ`). `limit` default 1000; `recent=true` returns newest first. `rawItem=true` returns raw items instead of filenames.
  Capture cadence is typically every 15–60 min; most cameras are daylight-only.
- **Image URL (verified, 2688×1520 for TX_Guadalupe_Rv_at_Comfort):**
  `https://usgs-nims-images.s3.amazonaws.com/overlay/<camId>/<filename>` — full-size frame with the USGS overlay text (timestamp/site label; mask it out of the registration region).
  Other prefixes from the camera record: `smallDir` → `https://usgs-nims-images.s3.amazonaws.com/720/<camId>/` (720-px version — use this for fleet-scale processing), `thumbDir`, `tlDir` (timelapse videos). [Verify `720/` returns the same filenames.]
  Direct S3 GETs need no credentials. Browser `fetch()` from other origins is blocked by CORS (irrelevant for Python).
- **Archive depth:** multi-year for older cameras (e.g. `IL_Lick_Creek_near_Woodside` has 24–25 images/day on 2024-01-01 and 2025-07-01). New cameras (e.g. Guadalupe at Comfort, created 2026-09-29) only have days.
- **License:** USGS says the product "for the most part, is in the public domain" but may contain copyrighted material. Do not redistribute images; publish manifests. Contact: hivis@usgs.gov / nims@usgs.gov.
- Python helper (official): `pyNIMS` (USGS, Jun 2026) — evaluate before writing our own client; our own thin client is in `src/riversight/data/nims.py`.

## 2. USGS Water Data OGC API (gauge readings = ground truth)
- **Instantaneous stage (15-min):**
  `GET https://api.waterdata.usgs.gov/ogcapi/v1/collections/continuous/items?monitoring_location_id=USGS-<nwisId>&parameter_code=00065&datetime=<startISO>/<endISO>&limit=<n>&f=json`
  (`v0` also still answers.) Example verified for `USGS-08167000` (Guadalupe Rv at Comfort).
  Response: GeoJSON `FeatureCollection`; each `feature.properties` has `time` (`2026-10-10T00:00:00+00:00`), `value` (**string**, e.g. `"3.35"`), `unit_of_measure` (`"ft"`), `parameter_code`, `statistic_id` (`00011` = instantaneous), `approval_status` (`Provisional`/`Approved`), `qualifier`, `time_series_id`, `last_modified`. Paginate via `links[rel=next]` / `offset`.
- Parameter codes: `00065` gage height (ft) — our target. `00060` discharge (cfs) — optional. Some sites report stage under a different time-series (check `numberReturned == 0` → try `daily` collection or skip the site).
- **API key:** optional, free: https://api.waterdata.usgs.gov/signup/ → pass `api_key=<key>` as a query param. Use it; rate limits without a key are unpublished.
- Max span per query is reportedly ~3 years; we request ≤35 days at a time.

## 3. NWS National Water Prediction Service (forecasts, for the agent)
- API docs: https://water.noaa.gov/about/api — stage forecasts/observations per NWS gauge (NWSLI). Map USGS site → NWSLI via the NWPS gauge list. Used only in the agent's "rapid rise" branch; not needed for the kill test.

## 4. Models (download at build time; record SHA256 in `models/MANIFEST.md`)
- ALIKED (`aliked-n16rot-top1k-640.onnx`) and LightGlue (`aliked_lightglue.onnx`): from the OpenCV GSoC project repo `YangGuanyuhan/lightglue_opencv_project` (ALIKED BSD-3; LightGlue Apache-2.0). Python: `cv2.ALIKED.create(path, cv2.ALIKED_Params())`, `cv2.LightGlueMatcher.create(path, score_threshold)` + `setPairInfo`.
- YuNet face detector (`face_detection_yunet_2023mar.onnx`, opencv_zoo) for privacy blur.
- Water segmentation: ours (trained on the 5090 from SAM2 pseudo-labels), exported to ONNX opset 17, validated in `cv2.dnn` new engine vs onnxruntime.

## 5. Existing public datasets (for comparability / prior art; do not claim "first dataset")
- USGS RISE imagery training dataset (CC0, 20 stations, 2016–2022, image + stage CSVs): https://www.usgs.gov/data/imagery-training-dataset-river-imagery-sensing-rise-application
- Johnson, Reneau & Komiskey 2025 (3 WI gauges, CC0): https://www.usgs.gov/data/time-lapse-imagery-image-derived-water-level-data-and-model-archive-three-usgs-streamgages
- GRIME-AI (Apache-2.0; HIVIS downloader + SAM2, no stage output): https://github.com/JohnStranzl/GRIME-AI
