# OpenCV 5 usage — every call that matters

Pinned: `opencv-python-headless==5.0.0.93` (the only 5.x wheel on PyPI; `docs/research/opencv5.md`). The live Graviton worker runs the COOL build of OpenCV; `/proof.json` records its `cv2.__file__`, version and `getBuildInformation()` hash.

**5.0** marks APIs that are new in OpenCV 5.0 and do not exist in 4.x. Every number in the evidence column comes from the committed file named there.

## 1. The stage-reading path (runs on every daylight frame, offline and live)

Order of execution: register → warp → block features → flood-height ROI → ridge → Kalman.

| call | where | what it does for us | what breaks without it | evidence |
|---|---|---|---|---|
| `cv2.ORB.create(3000)` + `BFMatcher(NORM_HAMMING)` | `vision/register.py` | Cheap first stage of the registration cascade. | — (baseline). On its own it registers 39.6 % of daylight frames. | `results/kill_test/registration_summary.csv`, `results/kill_test_v2_summary.json` |
| **5.0** `cv2.ALIKED.create(onnx, cv2.ALIKED_Params())` | `vision/register.py` | Learned keypoints and descriptors for the frames ORB cannot register (dawn and dusk light, haze, wet lens, seasonal change). Runs on 5.0's new DNN engine. | Registration falls from 95.7 % to the ORB level. ALIKED + LightGlue recovered **4,892** of 9,000 daylight frames. The scene model needs a registered frame, so those frames would have no reading. | same |
| **5.0** `cv2.LightGlueMatcher.create(onnx, 0.1)` + `setPairInfo()` + `match()` | `vision/register.py` | Learned matching of ALIKED descriptors that uses keypoint geometry. | Brute-force ratio-test matching of ALIKED descriptors gives far fewer correct matches across lighting change. | same |
| `cv2.findHomography(src, dst, cv2.USAC_MAGSAC, 3.0)` + `perspectiveTransform` | `vision/register.py` | Robust frame → reference homography. Inlier ratio and reprojection error become the registration score, which drives the `VIEW_CHANGE` flag. | Plain RANSAC needs per-site threshold tuning and is less stable on low-inlier frames. No registration-quality signal for the agent. | same |
| `cv2.warpPerspective` | `vision/scene_features.py`, `live/bundle.py` | Puts every frame into reference geometry so block *k* is the same patch of ground in every frame. Offline it uses `BORDER_REPLICATE`. On arm64 the live path pads with `copyMakeBorder(BORDER_REPLICATE)` and warps with `BORDER_CONSTANT`, avoiding KleidiCV issue #29816. | Blocks wander with camera jitter, and the flood-height map (h* per block) is meaningless. | `results/kill_test_v2.csv` (every test reading went through it) |
| `cv2.resize(INTER_AREA)` | `vision/scene_features.py`, `live/bundle.py`, `live/quality.py` | Area-downsizes the warped frame to 320 × 180 (80 × 45 = 3,600 blocks of 4 px). INTER_AREA everywhere also avoids the arm64 INTER_LINEAR 3-channel crash (#29794). | Full-resolution block features cost far more per frame; aliasing adds noise to the block statistics. | same |
| `cv2.cvtColor(BGR→Lab)` | `vision/scene_features.py` | Lab lightness (median-normalised per frame) and the a/b chroma of each block: wet vs dry rock, water colour. | No illumination-normalised appearance features. | same |
| `cv2.Sobel` (x, y) + `cv2.magnitude` | `vision/scene_features.py` | Gradient magnitude of L per block: ripples, whitewater, exposed rock texture. | Loses the texture channel that separates moving water from wet ground. | same |

These features feed the flood-height map and the kernel-ridge regressor (`calib/flood_height_map.py`, `calib/scene_regressor.py`, NumPy/SciPy). On the 20-day fit window the scene model met MAE ≤ 0.25 ft at **9/19** sites, against **1/20** for the classical transect detector it replaced (`results/kill_test_v2_summary.json`, `fit_window` block). On the frozen test days: **14/20** sites, median MAE **0.182** ft.

## 2. Camera QA (live flags and agent tools)

| call | where | what it does | what breaks without it |
|---|---|---|---|
| `cv2.Laplacian(CV_64F).var()`, `cvtColor(BGR→HSV / Gray)`, `erode` + `getStructuringElement` (dark channel) | `live/quality.py` | Sharpness, glare fraction, fog (dark-channel) score and mean brightness per frame → `LOW_QUALITY` flag and the agent's `image_quality` tool. | A fogged or wet lens yields a confident wrong stage; the agent can't tell a lens problem from a moved camera. |
| registration score (above) | `vision/register.py` | Inlier ratio < 0.25 or reprojection > 4 px → `VIEW_CHANGE`. | No view-change detection, and 8/20 cameras have history periods registered to a different view. |
| `cv2.phaseCorrelate` | agent tool `compare_to_last_good` (W2, `agent/tools.py`) | Sub-pixel global shift vs the last good frame: separates a nudged camera from a new view. | Agent can't tell "re-anchor" from "quarantine". (Row confirmed once W2's tool lands.) |

## 3. Privacy

| call | where | what it does | what breaks without it |
|---|---|---|---|
| `cv2.FaceDetectorYN.create` (YuNet ONNX) + `GaussianBlur` | `vision/privacy.py` | Blurs faces in every frame before it reaches a demo asset, the dashboard or an overlay. Fails closed if the model file is missing. | Non-negotiable 7 is violated; frames can't be published. |

## 4. Showing the flood

| call | where | what it does | what breaks without it |
|---|---|---|---|
| `cv2.applyColorMap(COLORMAP_JET / INFERNO)` + `findContours` / `drawContours` | `viz.py`, `scripts/scene_demo.py` | Draws the flood-height map (stage at which each patch floods) and the predicted wet area at a given stage, i.e. "what is under water at X ft". | No explainability layer, no flood-extent visual for the agent's alert. |
| `cv2.Animation` + `cv2.imwriteanimation` | `scripts/scene_demo.py` | Writes the event GIFs (frames + wet overlay + stage needle) natively, with no Pillow or imageio. | Extra imaging dependency. |
| `cv2.imencode` / `imdecode` | `agent/store.py` | JPEG round trip to and from S3 without temp files. | — |
| `putText`, `polylines`, `line`, `circle`, `arrowedLine` | `viz.py`, `killtest.py` | Time-series figures and overlays for the report without matplotlib. | — (presentation) |

## 5. Demoted (kept for QA and the ablation, not on the critical path)

The SLICE_01 classical waterline detector: `cv2.remap` sampling along transects, `Scharr`, `Laplacian`, `blur`, `cvtColor(HSV)` profiles, `connectedComponentsWithStats` + `morphologyEx` to cut transects across the stage-correlation map (`vision/transect.py`, `killtest.py`). It is the baseline the scene model beat (1/20 vs 9/19 above).

## 6. COOL on Graviton

The per-kernel COOL vs pip comparison covers exactly the kernels in §1: `imdecode`, `resize(INTER_AREA)`, `cvtColor(BGR→Lab)`, `warpPerspective`, `Sobel`, plus the ALIKED/LightGlue DNN stage and the whole per-frame pipeline. Results: `docs/COOL_BENCHMARK.md` and `results/cool_bench/` (in progress).

## Not used, on purpose

The water-segmentation net, `ANNIndex` and the `FontFace` overlays from the original plan were cut in the final sprint (`docs/PLAN_2026-10-22_FINAL_SPRINT.md`). Night/IR models were cut too.
