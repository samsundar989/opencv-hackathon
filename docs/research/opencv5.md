# OpenCV 5 deep-dive for the OpenCV AI Competition 2026 (status 2026-10-10)

**Method.** Primary sources: OpenCV wiki ([OpenCV-5](https://github.com/opencv/opencv/wiki/OpenCV-5), [migration](https://github.com/opencv/opencv/wiki/OpenCV-4-to-5-migration), [DNN benchmarks](https://github.com/opencv/opencv/wiki/OpenCV-5-DNN-Benchmarks), [2026 dev-meeting minutes](https://github.com/opencv/opencv/wiki/2026)), git history of the opencv repos, PyPI, issues, AWS listings. PyPI was blocked here, so I **built the 5.0.0 tag from source** (x86_64, Py3.13, NumPy 2.5) and probed it. **✔** = verified on that build (same bindings as the 5.0.0.93 wheel; wheel build flags not inspected).

## TL;DR
- Use **`opencv-python(-headless)==5.0.0.93`** and **pin it**. 5.1 is due "mid-October" and **removes `ENGINE_CLASSIC/ENGINE_NEW`, renumbers `EngineType` (AUTO=0, OPENCV=1, ORT=2) and `OPENCV_FORCE_DNN_ENGINE` values** ([#29341](https://github.com/opencv/opencv/pull/29341)).
- New DNN engine is **CPU-only**; CUDA/OpenCL backend/target requests are ignored with only a log warning ✔.
- Much of what is marketed as "OpenCV 5" exists only on the 5.x branch: XFeat, DISK-LightGlue, viz3d, visual-odometry/SLAM, point-cloud filtering/meshing, NumPy-style broadcasting (`texpr`), CUDA in the new engine, Python hand-eye.
- Graviton hazard: KleidiCV `resize` **SIGSEGV** in 5.0.0.93 arm64 wheels ([#29794](https://github.com/opencv/opencv/issues/29794), open).
- The "3d" module does not exist in 5.0.0: calib3d became **`geometry`, `calib`, `stereo`, `ptcloud`** (Python names unchanged).

## 1. Release status
| Item | Status |
|---|---|
| 5.0.0 | Tagged 2026-06-05, [released](https://github.com/opencv/opencv/releases/tag/5.0.0) 06-06; changelog "TBD". 4.14.0 followed in July. |
| pip | All four packages **5.0.0.93, 2026-07-02**, the only 5.x wheel ([PyPI](https://pypi.org/project/opencv-python/#history)). pip picks it over the later 4.14.0.94 (07-28). |
| Wheels | `cp37-abi3` (Requires-Python ≥3.6; CI-tested to 3.14; NumPy 1.19–2.5). manylinux2014 and manylinux_2_28 for **x86_64 and aarch64**, plus win32/win_amd64, macOS 14 x86_64 and macOS 13 arm64. Not in the wheels: CUDA, ONNX Runtime (ORT), OpenVINO, Windows-ARM64 (targeted ~5.1). |
| 5.x branch | 5.1.0-dev, default branch since August. VLM module deferred past 5.1 ([minutes](https://github.com/opencv/opencv/wiki/2026)). |
| To contrib | `ml`, `gapi`, Haar `CascadeClassifier` and `HOGDescriptor` (`xobjdetect`), and AKAZE/KAZE/BRISK/AGAST/BOW to `xfeatures2d` (with SURF, BRIEF, FREAK, DAISY). **Removed:** C API, OpenVX, and the Caffe, Darknet and Torch7 importers ✔. TF importer slated for removal. **Into main:** rgbd moved to `ptcloud`, and MCC to `cv2.mcc` ✔. |
| Packaging bug | The contrib 5.0.0.93 wheel lacks the `cv2.data` Haar XMLs and the G-API Python wrappers ([#1244](https://github.com/opencv/opencv-python/issues/1244)). The [fix](https://github.com/opencv/opencv-python/commit/e62d96fb4d216a11902e7618f92d6453f8f0c798) is unreleased. |

## 2. What's new: entry points and maturity (S = solid, C = usable with care, A = avoid)
| Area | Python API (✔ = present/ran) and notes | Rating |
|---|---|---|
| **DNN engine** | `cv2.dnn.readNetFromONNX(path, engine)` with `ENGINE_CLASSIC=1`, `NEW=2`, `AUTO=3` (default; tries new, falls back to classic) and `ORT=4` ✔. Typed graph, fusion, dynamic shapes and If/Loop. Vendored MLAS SGEMM ✔. Net exposes `getPerfProfile`, `getFLOPS` and `enableKVCache` ✔. ONNX coverage: ">64%" at 5.0, 72.9% (Jul) and 80% (Oct, 5.x-dev only). Attention/GELU/dynamic-batch test models match reference on all engines ✔. | C (validate every model vs ORT) |
| Models known to run | From OpenCV's own benchmark and test lists: YOLOv3–v10, YOLO-NAS, YOLOX, **YOLO26 n/m-seg**, RT-DETR-L, RF-DETR, OWLv2, Grounding-DINO-T, SAM2 (Hiera-L) enc/dec, SAMURAI, Depth-Anything-v2-S, DINOv2/v3, SigLIP, ViT/DeiT/BEiT, Segformer, BiRefNet, U2Net, RTMPose, PP-OCRv3, TrOCR, CRNN, NanoTrack, VitTrack, XFeat, Real-ESRGAN, SwinIR, NAFNet. **Errors:** RAFT (i7), SAM3 encoder (M1). YOLO11, D-FINE, CLIP and MobileSAM are not listed [unverified]. Sources: [benchmarks](https://github.com/opencv/opencv/wiki/OpenCV-5-DNN-Benchmarks), opencv_extra `testdata/dnn/download_models.py`. | C |
| CPU speed (ms, OpenCV vs ORT 1.25.1, i9) | YOLOv8 12.4/13.0; yolo26n 9.9/9.6; RT-DETR 119/100; RF-DETR 93/97; DepthAnything 135/127; DINOv2 21/27; OWLv2 1075/1543; G-DINO 1845/1862; SAM2 encoder 2351/2281, decoder 23/11. Outliers: CRNN 15.6/1.8, YuNet 4.0/2.3. On AMD, OpenCV is often 2–3× faster than ORT. 5.1-pre runs yolo26n at 0.8× ORT 1.30. | – |
| **LLM/VLM** | `cv2.dnn.Tokenizer.load(cfg)` with `encode/decode` ✔, and `net.enableKVCache()` ✔. Samples: `qwen_inference.py` (Qwen2.5-0.5B), `gemma3_inference.py` (1B), `gpt2_inference.py`, `vlm_inference.py` (PaliGemma2-3B: three ONNX files, **no KV-cache**), `ldm_inpainting.py`. In 5.0, any shape change re-packs all weights, which makes decoding slow (fixed later, [#29595](https://github.com/opencv/opencv/pull/29595)). | A as core, C as cameo |
| **features** | `cv2.ALIKED.create(onnx, cv2.ALIKED_Params())` (640² input) ✔; `cv2.DISK.create(onnx, maxKeypoints, scoreThreshold, imageSize)` ✔; `cv2.LightGlueMatcher.create(onnx, scoreThreshold)` + `setPairInfo()` ✔ (ALIKED-LightGlue only in 5.0); `cv2.detail.LightGlueFeaturesMatcher` for stitching ✔. Model sources: `aliked-n16rot-top1k-640.onnx` and `aliked_lightglue.onnx` (GSoC repo YangGuanyuhan/lightglue_opencv_project); DISK from fabio-sim/LightGlue-ONNX v0.1.0. Sample: `samples/cpp/example_features_aliked_lightglue.cpp`. | C |
| ANN | `cv2.ANNIndex.create(dim, dist)` with `addItems`, `build`, `knnSearch` and `save/load` (mmap) ✔ ran. | S−/C |
| **ptcloud** | `cv2.Volume(cv2.VolumeType_TSDF/HashTSDF/ColorTSDF, cv2.VolumeSettings(...))` with `integrate`, `integrateColor`, `raycast` and `fetchPointsNormals`. ✔ TSDF smoke test: a wall at 1.5 m raycasts to z=1.48. Also `cv2.Odometry` (DEPTH=ICP, RGB, RGB_DEPTH), `RgbdNormals`, `depthTo3d`, `registerDepth`, `findPlanes`, `Octree`, `load/savePointCloud` and `load/saveMesh` (.ply/.obj), `triangleRasterize*` ✔. Samples: `samples/python/volume.py`; `odometry.py` is broken on 5.x ([#30143](https://github.com/opencv/opencv/issues/30143)). | C |
| **calib** | `cv2.calibrateMultiview(objPoints, imagePoints, imageSize, detectionMask, models, …)` and `registerCameras` ✔: mixed pinhole/fisheye rigs, partial views, ChArUco. Plus `cv2.fisheye.*`. **`calibrateHandEye` and `calibrateRobotWorldHandEye` are missing from Python 5.0.0.93** ✔ ([#29565](https://github.com/opencv/opencv/issues/29565)). Docs: [tutorial](https://docs.opencv.org/5.0/tutorials/calib3d/camera_multiview_calibration/multiview_calibration.html), `apps/multiview-calibration/multiview_calibration.py`. | C |
| geometry | USAC is the default robust backend. `cv2.USAC_MAGSAC/ACCURATE/PARALLEL` and `UsacParams` ✔. New `approxPolyN` and `buildMST`. [USAC tutorial](https://docs.opencv.org/5.0/tutorials/calib3d/usac.html). | S |
| stereo | StereoBM/SGBM only; unchanged. | S (not 5-specific) |
| objdetect | `cv2.aruco.ArucoDetector/CharucoDetector`, `QRCodeDetector(Aruco)`, `cv2.barcode.BarcodeDetector`, `FaceDetectorYN/FaceRecognizerSF` ✔. `cv2.mcc.CCheckerDetector` is new to main ✔ (API changes undocumented, [#29705](https://github.com/opencv/opencv/issues/29705)). | S |
| tracking | `TrackerNano`, `TrackerDaSiamRPN`, `TrackerVit` and `TrackerMIL` ✔. GOTURN removed (Caffe); KCF/CSRT stay in contrib. Since 4.11, TrackerVit's input scale for G/B comes out negated: `1.0/Scalar` is quaternion inversion ([#30164](https://github.com/opencv/opencv/issues/30164), open). | Nano C; Vit A |
| optical flow | DIS, Farneback, VariationalRefinement and SparsePyrLK ✔ (KleidiCV LK on Arm). | S |
| videoio | Context managers ✔. `get()` returns −1 for unsupported properties ✔. Wheels likely bundle FFmpeg 8.1.1 (CVE-2026-8461); no AV1 decode in Linux 5.0 wheels ([#1276](https://github.com/opencv/opencv-python/issues/1276)). | S |
| core | New `CV_Bool/32U/64U/64S/16BF` types, 1-D/0-D Mats, `MatShape`, built-in LAPACK. From Python: **`np.int64/uint64` are silently cast to int32** (2⁴⁰ became 0 ✔); bool arithmetic asserts ✔; bool masks work ✔; float16 is unsupported in GaussianBlur ✔. Broadcasting arithmetic is **5.x-dev only** ([#29426](https://github.com/opencv/opencv/pull/29426)). | C/A |
| imgproc | Exact bilinear/bicubic warps: 10–300% faster, with numerically different output. Pillow-compatible `INTER_NEAREST`. STB TrueType `cv2.FontFace("sans"/"italic"/"uni"/path)` + `putText(img, text, org, color, fface, size[, weight, flags, wrap])` with UTF-8 ✔. **TRUCO contours run only for `RETR_LIST`, no hierarchy, 8UC1. The Python wrapper always requests hierarchy, so Python never reaches TRUCO** ✔. In C++ on a 4000² image (2 vCPU): 24.7 ms TRUCO vs 62 ms classic vs 95 ms from Python. | S (TRUCO: C++ only) |

**1-D gotchas ✔:** `HoughLinesP` returns (N,4), not (N,1,4) ([#29637](https://github.com/opencv/opencv/issues/29637)). Old quirk: vectors of length ≤4 act as Scalars, so multiplying two 3-vectors gives 4×1 ([#1243](https://github.com/opencv/opencv-python/issues/1243)). Contours and `goodFeaturesToTrack` shapes are unchanged.

## 3. GPU (RTX 5090, sm_120)
- **Pip wheels have no CUDA.** The new engine ignores CUDA/OpenCL targets ✔. `ENGINE_ORT` without ORT falls back to AUTO with only a warning ✔. `ENGINE_CLASSIC`+CUDA in a non-CUDA build throws an assertion ✔. The OpenCL T-API (`cv2.UMat`) still accelerates imgproc on NVIDIA [check `cv2.ocl.haveOpenCL()`]; contrib CUDA modules need a source build.
- **Option A (best): ORT inside OpenCV.**
  - Build: compile 5.0.0 with `-DWITH_ONNXRUNTIME=ON -DDOWNLOAD_ONNXRUNTIME_GPU=ON`, which fetches ORT **1.25.1** GPU.
  - Use: call `readNetFromONNX(path, engine=ENGINE_ORT)` + `setPreferableTarget(DNN_TARGET_CUDA)`. This runs ORT's CUDA execution provider (EP) on device 0, while OpenCV keeps blobs, NMS and geometry.
  - Pitfalls: if the EP fails, it falls back to CPU **with only a warning**, so assert on latency. Models load from a file path only. There is no TensorRT EP. It needs CUDA 12 and cuDNN 9 libraries. Blackwell support in the 1.25.1 binaries is [unverified]; smoke-test first.
- **Option B: classic CUDA backend.**
  - Build: `WITH_CUDA, WITH_CUDNN, OPENCV_DNN_CUDA, CUDA_ARCH_BIN=12.0`. The 5.0 CMake knows Blackwell 10.0–12.1, and CUDA 13 has been supported since 4.13.
  - Use: `ENGINE_CLASSIC` + `DNN_TARGET_CUDA_FP16`.
  - Limits: the classic importer lacks many transformer ops, and it is removed in 5.1.
- **5.1-dev:** native new-engine CUDA ([#29286](https://github.com/opencv/opencv/pull/29286); ResNet50 1.24 ms vs ORT 1.42), a CUDA UMat allocator and cuDNN-JIT. The whole graph drops to CPU if any op lacks a CUDA kernel. Unreleased; skip.

## 4. Arm / Graviton / COOL
- **KleidiCV.** The HAL is on by default for AArch64 Linux/macOS/Android since 4.13, and 5.0.0 pins **KleidiCV 26.03**. It covers parts of remap/warpPerspective, linear resize downscale (⅓–1), Gaussian/median blur, YUV, sepFilter2D and LK flow, on Neon, SVE2 and SME ([Arm blog](https://developer.arm.com/community/arm-community-blogs/b/ai-blog/posts/what-s-new-in-kleidicv-26-03-for-computer-vision-on-arm-cpus)). Wheel inclusion is inferred from #29794 backtraces.
- **Open ARM issues:** the #29794 crash (3-channel `INTER_LINEAR`, scale just below 1) and [#29816](https://github.com/opencv/opencv/issues/29816) (warpPerspective `BORDER_REPLICATE` is inaccurate). Maintainers call KleidiCV resize "not quite compliant", so ARM output differs from x86.
- **DNN on aarch64** uses MLAS NEON SGEMM. No public issue backs the reported "new engine crashes on Linux ARM64" [unverified].
- **What COOL is:** a closed, prebuilt, Graviton-tuned OpenCV 5 (custom kernels and threading on top of KleidiCV).
  - [G4](https://aws.amazon.com/marketplace/pp/prodview-fdvbfiewzuehs): COOL 3.1 on OpenCV 5.0, Python 3.10–3.12, benchmarked against stock 5.0.0 on 78 functions.
  - [G5](https://aws.amazon.com/marketplace/pp/prodview-igdweaoo6prb6): "OpenCV 5.1.0", "KleidiCV 0.7.0" (pre-26.03 numbering), Python 3.12–3.14, Neoverse-V3 only. License is checked via IMDS; video needs `/opt/ffmpeg/lib`.
- **COOL numbers:** internal +20.6% (G4), +21.8% (G3), +23% over 102 kernels (G5) vs vanilla 5.0; AWS's 1.2→1.6 fps is vs **pip 4.12** ([blog](https://aws.amazon.com/blogs/spatial/accelerating-opencv-on-graviton-the-cool-framework)). Stock 5.0.0.93 aarch64 already has KleidiCV: expect small deltas, measure per kernel.
- **G5 caveat:** "5.1.0" may carry the 5.1 enum changes; check `cv2.dnn.ENGINE_*` on the AMI [inference].

## 5. Bugs that can bite in 16 days (5.0.0 / 5.0.0.93)
- **Python:**
  - Hand-eye calibration missing (#29565).
  - Arrays with more than 128 channels silently lose the channel axis ([#29586](https://github.com/opencv/opencv/issues/29586)).
  - `import cv2` appends an empty `LD_LIBRARY_PATH` entry, which child processes resolve to CWD ([#1268](https://github.com/opencv/opencv-python/issues/1268)).
  - Plus the 1-D shape changes above.
- **DNN correctness, fixed only on 5.x:**
  - GELU(tanh) is computed as exact GELU ([#30104](https://github.com/opencv/opencv/pull/30104)).
  - Batched broadcast MatMul (#30097).
  - Softmax for opset < 13 (#30106), GRU (#30101), Cast after Gather (#29621), Einsum (#29829).
  - **Diff every model against ORT.**
- **imgproc, fixed post-5.0:**
  - warpAffine infinite loop ([#29867](https://github.com/opencv/opencv/pull/29867)) and warp pointer overflow (#30137).
  - medianBlur with ksize ≥ 257 crashes (#30121).
  - Lanczos remap on new depths (#30155).
- **calib, fixed post-5.0:** 4-coefficient distortion handling (#29910) and fisheye extrinsic refinement (#30070).
- **New dtypes:**
  - inRange on `CV_Bool` segfaults (#30153).
  - `sum` wraps at 32 bits (#30002).
  - `convertTo` saturation for 64U/64S/32U/16BF (#29964, #29996, #30198, #30205).
- **Contrib:** wechat_qrcode no longer accepts its Caffe models ([#29712](https://github.com/opencv/opencv/issues/29712)).
- **Tracking:** the TrackerVit scaling bug (#30164).

## 6. Showcase picks for Bradski and Nelson
1. **Engine-explicit ONNX stack:** YOLO26/RF-DETR + Depth-Anything-v2 + DINOv2 via `engine=ENGINE_NEW`, `getPerfProfile` per layer. Demo: live new-vs-classic-vs-ORT table (ms, max-abs-diff) on Graviton.
2. **Open-vocabulary "find X" agent tool:** OWLv2 or Grounding-DINO-T in cv::dnn (~1–2 s/frame on an i9). Demo: agent asks for "unripe strawberry", gets boxes, zooms, recaptures.
3. **SAM2 in OpenCV:** run the encoder per keyframe and the decoder per prompt (20–50 ms). Demo: detector box → SAM2 mask → `geometry` measurements (`minAreaRect`, `contourArea`).
4. **ALIKED + LightGlue + `USAC_MAGSAC`.** Demo: relocalize against a reference map across lighting/season; inlier ratio decides accept/re-take/move; panorama via `LightGlueFeaturesMatcher`.
5. **`ANNIndex` visual memory** over cv::dnn DINOv2/SigLIP embeddings. Demo: "seen this plant, defect or place before?" with an mmap-persisted index.
6. **ptcloud reconstruction:** RGB-D → `Odometry` (ICP) → `Volume(ColorTSDF)` → `saveMesh(.ply)`. Demo: scan a plant/shelf, export the mesh, measure height/volume.
7. **`calibrateMultiview`** on a ChArUco rig with mixed pinhole/fisheye cameras. Demo: a reprojection-error table and extrinsics plot, then live triangulation.
8. **`cv2.mcc.CCheckerDetector` (new to main).** Demo: color-calibrated crop-ripeness scoring under changing sun (Bradski's ag focus).
9. **C++ service on COOL.** Demo: TRUCO `findContours(RETR_LIST)` (2.6× here) plus the new warps, A/B vs pip 5.0.0.93 (p50/p95, $/1k frames). The only route to TRUCO.
10. **Unicode `FontFace` HUD** plus a small in-dnn LLM cameo (Qwen2.5-0.5B with KV-cache) as an offline fallback narrator, kept off the critical path.

**Avoid:**
- Claiming the new engine uses the GPU.
- Hard-coding engine names or numbers (the 5.1 break).
- Haar, HOG, `ml`, G-API, and Caffe/Darknet models.
- Python hand-eye calibration.
- Features that exist only on 5.x-dev, unless built from a pinned commit in Docker.
- 64-bit, bool or bf16 numerics from Python.
- TrackerVit as-is; RAFT or SAM3 on the new engine; the interactive PaliGemma VLM.
- On Graviton: 3-channel `INTER_LINEAR` resize near scale 1 (use `INTER_AREA` or 4 channels) and `BORDER_REPLICATE` warps.
- Any claim of a Python TRUCO speedup.

_Saved to `/tmp/claude-0/-home-claude/6fecd807-30aa-5eb1-a919-92099c30d93b/scratchpad/research/C_opencv5.md`; probe scripts and the 5.0.0 build are in that scratchpad._
