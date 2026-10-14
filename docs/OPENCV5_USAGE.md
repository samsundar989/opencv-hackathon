# OpenCV 5 usage — every call that matters

Pinned: `opencv-python-headless==5.0.0.93`. Each row: what the call does in RiverSight, and what breaks without it.
Evidence column points at code and (once produced) at a committed result. Updated as slices land.

| Call (module) | Where | What it does for us | What breaks without it | Evidence |
|---|---|---|---|---|
| `cv2.ALIKED.create(onnx, ALIKED_Params())` (features, **5.0-only**) | `vision/register.py` | Learned keypoints + descriptors on every frame the cheap ORB stage cannot register (dawn/dusk light, haze, wet lens). Runs through the new DNN graph engine. | SLICE_01, 20 sites × 30 days, 9,000 true-daylight frames (sun-elevation QA): cascade registered 8,611 (95.7%); ORB+MAGSAC alone 3,567 (≈40%); **ALIKED+LightGlue rescued 4,892**; chaining 152. Without it the 90% registration bar fails by a wide margin. | `results/kill_test/registration_summary.csv` (`scripts/registration_summary.py`) |
| `cv2.LightGlueMatcher.create(onnx, thr)` + `setPairInfo(qKpts, tKpts, qSize, tSize)` + `match()` (features, **5.0-only**) | `vision/register.py` | Learned matching of ALIKED descriptors using keypoint geometry. | Brute-force/ratio-test matching of ALIKED descriptors gives far fewer correct matches under illumination change. | same |
| `cv2.findHomography(..., cv2.USAC_MAGSAC, 3.0)` (calib3d USAC) | `vision/register.py` | Robust frame→reference homography; inlier count + reprojection error become the registration score used for QA (`CAMERA_MOVED`). | Plain RANSAC needs threshold tuning per site and is less stable on low-inlier frames. | |
| `cv2.ORB.create` + `BFMatcher(NORM_HAMMING)` | `vision/register.py` | Cheap first stage of the registration cascade; ablation baseline. | — (baseline) | |
| `cv2.warpPerspective` (imgproc, 5.x warp path) | `vision/register.py`, `killtest.py` | Puts every frame into reference coordinates so transects are fixed polylines; also warps validity masks for the correlation map. | Transects drift with camera jitter → waterline position is meaningless. | |
| `cv2.remap` (bilinear) | `vision/transect.py` | Samples a band along each transect polyline (1-D profiles). | Need slow per-pixel Python sampling. | |
| `cv2.Scharr`, `cv2.magnitude`, `cv2.Laplacian`, `cv2.blur`, `cv2.cvtColor` (BGR→HSV/Gray) | `vision/transect.py` | Profile features: gradient, texture energy, saturation, hue → boundary detection. These are COOL-accelerated kernels on Graviton (S07). | No classical waterline. | |
| `cv2.connectedComponentsWithStats`, `cv2.morphologyEx` | `killtest.py` | Turns the per-pixel stage-correlation map into bands; transects are cut across each band. | Transects must be hand-drawn per site. | |
| `cv2.applyColorMap`, `cv2.polylines`, `cv2.putText`, `cv2.circle` | `killtest.py` | Overlays and time-series figures for the report (no matplotlib dependency). | — (presentation) | |
| `cv2.dnn` new engine (`ENGINE_NEW`) | used implicitly by ALIKED/LightGlue; explicitly in S03 (water seg net) | ALIKED/LightGlue log "Targets are not supported by the new graph engine" → they run on the new CPU engine. | — | S03 latency table |

Planned (later slices): `cv2.dnn.readNet(..., engine=cv2.dnn.ENGINE_NEW)` + `getPerfProfile` for the water-seg net (S03), `ANNIndex` reference bank (S02), `FontFace` Unicode overlays (S05), `FaceDetectorYN` (YuNet) privacy blur (S05).
