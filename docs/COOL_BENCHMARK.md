# COOL benchmark: COOL OpenCV vs stock pip OpenCV 5.0.0.93 on Graviton

**Status:** harness done and validated on the dev box; the AWS run waits for the COOL Marketplace subscription and AWS sign-in (Q-0008). Every number below is generated from `results/cool_bench/` by `bench/build_cool_doc.py`.

## Question

RiverSight's live worker reads one frame per camera every 15 minutes (the original plan said 30; the cost tables give both). Does the COOL build of OpenCV on Graviton make that cheaper or faster than the stock pip wheel, stage by stage and for the whole fleet, and does it give the same answers?

## Arms

All arms run on **the same instance**, launched from the COOL G5 AMI and terminated by the script:

| arm | OpenCV | Python |
|---|---|---|
| **cool** | the AMI's COOL build (version and `getBuildInformation()` hash recorded) | the AMI's newest venv |
| **pip-5.0.0.93** | `opencv-python-headless==5.0.0.93` in a clean venv | same interpreter version where the AMI allows |

The stock aarch64 5.0.0.93 wheel already includes Arm's KleidiCV HAL, so this is COOL against an already Arm-optimised baseline, not against an unoptimised build. Each arm records its KleidiCV status.

## Workloads

What the live worker actually runs, in `src/riversight/live/bundle.py` and `vision/register.py`, timed stage by stage on 20 real frames (one registered daylight frame per calibrated camera, 720 px, from the USGS HIVIS cache):

| stage | OpenCV | notes |
|---|---|---|
| `imdecode` | JPEG decode | |
| `register_orb_magsac` | ORB, BFMatcher, USAC_MAGSAC homography | first stage of the cascade |
| `register_aliked_lightglue_magsac` | ALIKED + LightGlueMatcher (new DNN engine) + MAGSAC | runs only when ORB fails |
| `warpPerspective` | `copyMakeBorder(REPLICATE)` + `warpPerspective(INTER_LINEAR, BORDER_CONSTANT)` | the arm64-safe warp |
| `resize_area` | `resize(INTER_AREA)` to 320 × 180 | |
| `cvtColor_lab` | BGR → Lab | |
| `sobel_magnitude` | `Sobel` x, y + `magnitude` | |
| `block_features` | the above + NumPy block statistics | |
| `ridge_predict` | NumPy only (control: should not change) | |
| `frame_pipeline` | the whole per-frame path, cascade included | |

**Fleet cycles:** the whole pipeline over (a) the 20 calibrated cameras, one frame each, repeated 5 times; and (b) 880 frames from the same cache (44 per camera), roughly one frame for every public HIVIS camera next to a gauge. This is "the whole HIVIS fleet" in compute, using our 20 site models.

## Method

- Two thread regimes: 1 thread, pinned to one core with `sched_setaffinity`; and all cores (`nproc`).
- 50 warm-up and 300 timed iterations per stage. The two ALIKED stages take seconds per call on CPU, so they use 10 warm-up and 100 timed iterations (`--dnn-iters`).
- Per stage: mean, p50, p95, p99 latency, throughput, and CPU utilisation (process CPU time ÷ wall time).
- **Equivalence:** every pixel stage's output on the 20 frames is saved per arm and compared: max |difference| and PSNR, plus the stage estimate in feet with fixed and with live registration.
- **Cost:** $ per camera-month at one frame per camera every 15 minutes (deployed) and every 30 minutes, counting day and night (conservative: the live worker skips night). EC2 on-demand price from the AWS Price List API at run time; COOL fee from the Marketplace listing. Also cameras per instance, the break-even speedup for COOL's fee, and a fleet-scaling table (cameras → cycle time, instances, $/month).
- **Provenance:** `cv2.__file__`, version, `getBuildInformation()` sha256 and full text, CPU model, AMI id and the EC2 instance-identity document, in `results/cool_bench/<run>/<arm>/provenance.json`.
- **Amdahl breakdown:** each stage's share of the per-frame time, so the end-to-end number can be read against the per-kernel ones.

## Honesty rules

- Slowdowns are reported as slowdowns.
- The DNN stages (ALIKED + LightGlue) are not what COOL's classical kernels target, and they dominate the frame time whenever ORB fails. Those stages are reported separately, so the end-to-end ratio is not dressed up by the kernels.
- The dev-box run below is x86 on a shared workstation. It validates the harness and gives scale; it says nothing about COOL.

## Results

### Dev box (x86, harness validation, pip arm only)

Windows 11 workstation shared with other jobs, run through the local job queue with 8 cores reserved. Caveats that apply only here: Windows cannot pin the 1-thread regime to a core; CPU utilisation is coarse (process time ticks at 15.6 ms) and includes OpenCV's spinning worker threads; other jobs share the machine. Use these numbers for scale (which stages dominate the frame time), not for speed claims. Three things they do show: ALIKED + LightGlue costs seconds per frame on CPU, so the cascade's ORB-first design matters; the classical kernels COOL targets cost a millisecond or less each; and the fleet cycle is dominated by the frames ORB cannot register.

<!-- BEGIN:cool:devbox_x86_2026-10-23 -->
**Provenance**

- **pip-5.0.0.93:** OpenCV 5.0.0 from `C:\Users\samsu\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\cv2\__init__.py`, build-info sha256 `ce2f2890911c…`, KleidiCV no, Python 3.14.4, AMD64 Family 26 Model 68 Stepping 0, AuthenticAMD, 16 cores; AMD64, not EC2.

**Per-stage latency, pip-5.0.0.93**

| threads | stage | n | p50 ms | p95 ms | p99 ms | CPU util |
|---|---|---|---|---|---|---|
| 1 | imdecode | 300 | 0.860 | 1.549 | 1.640 | 1.03 |
| 1 | register_orb_magsac | 300 | 67.3 | 113.8 | 187.2 | 0.91 |
| 1 | register_aliked_lightglue_magsac | 30 | 1913.4 | 2141.4 | 3554.1 | 0.96 |
| 1 | warpPerspective | 300 | 1.357 | 2.106 | 2.915 | 1.00 |
| 1 | resize_area | 300 | 0.622 | 0.794 | 1.021 | 1.05 |
| 1 | cvtColor_lab | 300 | 0.140 | 0.159 | 0.282 | 1.08 |
| 1 | sobel_magnitude | 300 | 0.039 | 0.055 | 0.071 | 1.25 |
| 1 | block_features | 300 | 1.871 | 2.253 | 2.473 | 0.96 |
| 1 | ridge_predict | 300 | 0.021 | 0.046 | 0.130 | 0.00 |
| 1 | frame_pipeline | 30 | 112.4 | 2036.1 | 2277.7 | 0.98 |
| 8 | imdecode | 300 | 0.843 | 1.411 | 1.696 | 0.95 |
| 8 | register_orb_magsac | 300 | 18.9 | 24.2 | 29.2 | 5.02 |
| 8 | register_aliked_lightglue_magsac | 30 | 705.8 | 855.4 | 969.6 | 5.89 |
| 8 | warpPerspective | 300 | 0.564 | 0.784 | 0.863 | 4.34 |
| 8 | resize_area | 300 | 0.629 | 0.784 | 0.870 | 1.05 |
| 8 | cvtColor_lab | 300 | 0.138 | 0.155 | 0.299 | 1.06 |
| 8 | sobel_magnitude | 300 | 0.045 | 0.063 | 0.090 | 1.10 |
| 8 | block_features | 300 | 1.753 | 2.265 | 2.441 | 0.98 |
| 8 | ridge_predict | 300 | 0.022 | 0.087 | 0.128 | 0.00 |
| 8 | frame_pipeline | 30 | 26.7 | 732.2 | 734.8 | 5.91 |

**Fleet cycles** (mean over repeats; `registered` = frames the cascade registered)

| arm | threads | fleet | repeats | wall_s | frames_per_s | registered | cpu_util |
|---|---|---|---|---|---|---|---|
| pip-5.0.0.93 | 1 | 20 | 5 | 20.6 | 0.98 | 20 | 0.93 |
| pip-5.0.0.93 | 1 | 880 | 1 | 1166.7 | 0.75 | 756 | 0.91 |
| pip-5.0.0.93 | 8 | 20 | 5 | 6.9 | 2.88 | 20 | 5.79 |
| pip-5.0.0.93 | 8 | 880 | 1 | 392.7 | 2.24 | 756 | 5.87 |
<!-- END:cool:devbox_x86_2026-10-23 -->

### AWS m9g.large (Graviton5), COOL vs pip

_Pending the AWS run (`python bench/run_cool_bench.py --bucket … --ami … --cool-price …`)._

## Reproduce

```bash
python bench/make_pack.py                     # builds data/bench_pack (local frame cache; private, never committed)
python bench/cool_bench.py --out results/cool_bench/<run> --arm <label>     # one arm, this interpreter's cv2
python bench/compare_arms.py results/cool_bench/<run> --baseline pip-5.0.0.93
python bench/run_cool_bench.py --bucket <private bucket> --ami <COOL G5 AMI> --cool-price <USD/h>   # all of it on AWS
```
