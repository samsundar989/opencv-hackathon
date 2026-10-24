# COOL benchmark: COOL OpenCV vs stock pip OpenCV 5.0.0.93 on Graviton

**Status:** done. COOL G5 vs stock pip OpenCV 5.0.0.93 on the same m9g.large (Graviton5), 2026-10-24, run `cool_g5_m9g_2026-10-24`. Every number below is generated from `results/cool_bench/` by `bench/build_cool_doc.py`.

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

One command: `python bench/run_cool_bench.py --bucket <bucket> --ami ami-0d9a06f3c16d66f9e --cool-price 0.005`. Both arms ran on one m9g.large instance from the COOL G5 AMI, one after the other, on the same Python 3.14 interpreter with the same numpy (COOL's 2.5.3), so OpenCV is the only difference. The instance cost about $0.16 (`spend.json`); the COOL fee used in the cost tables is the Marketplace listing's approximate rate (`prices.json`).

**Bottom line.** One m9g.large running COOL covers **all ~880 gauged HIVIS cameras at a 15-minute cadence for about $0.06 per camera-month** ($0.0586 including COOL's fee; one cycle over 880 frames takes about 627 s of the 900 s budget). Provenance for every number: the instance-identity document, AMI id, `cv2.__file__`, version and `getBuildInformation()` hash of each arm, in `provenance.json` and `build_info.txt`. COOL gives bit-identical outputs. End to end it is flat on our workload, because about 98 % of a frame's time is the learned matcher (DNN), which COOL does not accelerate. On the classical registration path it is 1.16–1.21× faster.

![Where a frame's time goes](../results/cool_bench/cool_g5_m9g_2026-10-24/amdahl.png)

_`bench/plot_amdahl.py`, from `amdahl.csv`: per-call means of each stage, both cores. The DNN stage runs only on frames ORB cannot register, so per frame the classical share is larger than shown; the end-to-end fleet numbers below include that mix._

**What we found** (all figures from the generated tables below):

- **End to end, COOL is flat.** Fleet throughput over 880 frames is within 1 % of stock: 1.0019× on one thread and 1.0067× on both cores. That matches what other competitors reported (`docs/research/2026-10-22_rivals.md`).
- **The one clear win is ORB registration:** 1.16× on one thread and 1.21× on two (ORB + BFMatcher + USAC_MAGSAC). Most frames register with ORB alone, so the typical frame (p50 of the whole per-frame path) is 1.13× / 1.21× faster.
- **The classical kernels COOL targets show nothing on this workload:** `resize(INTER_AREA)`, `cvtColor(BGR→Lab)`, `Sobel`, `warpPerspective` and `imdecode` are all within about ±3 % (0.975× to 1.011×). Our images are small (720 px in, 320 × 180 working size), so each call costs well under 2 ms. The stock aarch64 wheel already ships Arm's KleidiCV HAL (`provenance.json`: `kleidicv: true` for both arms), so COOL is competing with an already Arm-optimised baseline.
- **The fleet cycle is Amdahl-bound by the DNN.** ALIKED + LightGlue takes about 98 % of the summed stage time (`amdahl.csv`) and is the same in both builds (0.996× / 0.999×). It runs on OpenCV's DNN engine, which COOL does not accelerate here. A speedup on everything else can't move the end-to-end number much.
- **Identical outputs.** Every pixel stage is bit-identical between the builds (max |diff| 0, PSNR ∞), and so is the stage estimate with fixed registration. With live registration the stage differs by at most 0.00044 ft across the 20 sites (`equivalence.csv`).
- **Cost:** with COOL's fee, COOL breaks even only at a 1.051× speedup, and the measured fleet speedup is below that. So COOL costs slightly more per camera-month: $0.0586 vs $0.0562 at the deployed 15-minute cadence, $0.0293 vs $0.0281 at 30 minutes. Either way, **one m9g.large covers all ~880 gauged HIVIS cameras** at a 15-minute cadence (one cycle takes about 627 s of the 900 s budget): roughly $74/month with COOL, $70 without, i.e. under a dime per camera-month (`cost.csv`, `scaling.csv`).
- **Why we still run COOL live:** same answers, a real ORB speedup, and no cost penalty that matters at this scale. Batching the fleet so COOL's kernels see larger images is the obvious next experiment (PLAN, optional), and so is moving the DNN stage to a faster engine.

<!-- BEGIN:cool:cool_g5_m9g_2026-10-24 -->
**Provenance**

- **cool:** OpenCV 5.1.0-dev from `/opt/cool/python_3.14/site-packages/cv2/python-3.14/cv2.cpython-314-aarch64-linux-gnu.so`, build-info sha256 `d3a4bed98ab0…`, KleidiCV yes, Python 3.14.4, 0xd84, 2 cores; m9g.large us-east-2, AMI `ami-0d9a06f3c16d66f9e`.
- **pip-5.0.0.93:** OpenCV 5.0.0 from `/opt/pipvenv/lib/python3.14/site-packages/cv2/__init__.py`, build-info sha256 `4460ffe25568…`, KleidiCV yes, Python 3.14.4, 0xd84, 2 cores; m9g.large us-east-2, AMI `ami-0d9a06f3c16d66f9e`.

**Per-stage latency, cool**

| threads | stage | n | p50 ms | p95 ms | p99 ms | CPU util |
|---|---|---|---|---|---|---|
| 1 | imdecode | 300 | 1.083 | 1.605 | 1.617 | 1.00 |
| 1 | register_orb_magsac | 300 | 38.5 | 45.7 | 48.7 | 1.00 |
| 1 | register_aliked_lightglue_magsac | 100 | 2064.7 | 2077.5 | 2104.0 | 1.00 |
| 1 | warpPerspective | 300 | 1.426 | 1.886 | 1.891 | 1.00 |
| 1 | resize_area | 300 | 0.694 | 0.756 | 0.775 | 1.00 |
| 1 | cvtColor_lab | 300 | 0.124 | 0.129 | 0.134 | 1.00 |
| 1 | sobel_magnitude | 300 | 0.078 | 0.088 | 0.094 | 1.00 |
| 1 | block_features | 300 | 1.678 | 1.798 | 1.819 | 1.00 |
| 1 | ridge_predict | 300 | 0.022 | 0.041 | 0.047 | 2.10 |
| 1 | frame_pipeline | 100 | 50.8 | 2121.3 | 2131.5 | 1.00 |
| 2 | imdecode | 300 | 1.084 | 1.606 | 1.617 | 1.00 |
| 2 | register_orb_magsac | 300 | 23.1 | 27.6 | 28.7 | 1.70 |
| 2 | register_aliked_lightglue_magsac | 100 | 1160.4 | 1162.9 | 1164.2 | 1.95 |
| 2 | warpPerspective | 300 | 0.782 | 1.031 | 1.038 | 2.00 |
| 2 | resize_area | 300 | 0.704 | 0.760 | 0.772 | 1.00 |
| 2 | cvtColor_lab | 300 | 0.124 | 0.128 | 0.132 | 1.00 |
| 2 | sobel_magnitude | 300 | 0.078 | 0.088 | 0.092 | 1.00 |
| 2 | block_features | 300 | 1.679 | 1.800 | 1.818 | 1.00 |
| 2 | ridge_predict | 300 | 0.023 | 0.042 | 0.046 | 1.97 |
| 2 | frame_pipeline | 100 | 34.9 | 1194.0 | 1194.8 | 1.93 |

**Per-stage latency, pip-5.0.0.93**

| threads | stage | n | p50 ms | p95 ms | p99 ms | CPU util |
|---|---|---|---|---|---|---|
| 1 | imdecode | 300 | 1.069 | 1.584 | 1.597 | 1.00 |
| 1 | register_orb_magsac | 300 | 44.6 | 52.3 | 54.5 | 1.00 |
| 1 | register_aliked_lightglue_magsac | 100 | 2055.7 | 2059.8 | 2061.6 | 1.00 |
| 1 | warpPerspective | 300 | 1.411 | 1.866 | 1.870 | 1.00 |
| 1 | resize_area | 300 | 0.700 | 0.763 | 0.774 | 1.00 |
| 1 | cvtColor_lab | 300 | 0.121 | 0.125 | 0.130 | 1.00 |
| 1 | sobel_magnitude | 300 | 0.076 | 0.087 | 0.091 | 1.00 |
| 1 | block_features | 300 | 1.676 | 1.795 | 1.820 | 1.00 |
| 1 | ridge_predict | 300 | 0.022 | 0.041 | 0.046 | 1.97 |
| 1 | frame_pipeline | 100 | 57.3 | 2116.4 | 2137.9 | 1.00 |
| 2 | imdecode | 300 | 1.070 | 1.587 | 1.598 | 1.00 |
| 2 | register_orb_magsac | 300 | 28.0 | 34.9 | 35.7 | 1.61 |
| 2 | register_aliked_lightglue_magsac | 100 | 1159.7 | 1162.0 | 1162.8 | 1.94 |
| 2 | warpPerspective | 300 | 0.772 | 1.021 | 1.027 | 2.00 |
| 2 | resize_area | 300 | 0.712 | 0.782 | 0.804 | 1.00 |
| 2 | cvtColor_lab | 300 | 0.121 | 0.124 | 0.129 | 1.00 |
| 2 | sobel_magnitude | 300 | 0.076 | 0.086 | 0.091 | 1.00 |
| 2 | block_features | 300 | 1.668 | 1.788 | 1.815 | 1.00 |
| 2 | ridge_predict | 300 | 0.022 | 0.045 | 0.046 | 2.10 |
| 2 | frame_pipeline | 100 | 42.2 | 1198.1 | 1199.9 | 1.92 |

**Fleet cycles** (mean over repeats; `registered` = frames the cascade registered)

| arm | threads | fleet | repeats | wall_s | frames_per_s | registered | cpu_util |
|---|---|---|---|---|---|---|---|
| cool | 1 | 20 | 5 | 19.4 | 1.03 | 20 | 1.00 |
| cool | 1 | 880 | 1 | 1106.8 | 0.80 | 757 | 1.00 |
| cool | 2 | 20 | 5 | 11.0 | 1.82 | 20 | 1.93 |
| cool | 2 | 880 | 1 | 627.3 | 1.40 | 757 | 1.93 |
| pip-5.0.0.93 | 1 | 20 | 5 | 19.4 | 1.03 | 20 | 1.00 |
| pip-5.0.0.93 | 1 | 880 | 1 | 1108.9 | 0.79 | 757 | 1.00 |
| pip-5.0.0.93 | 2 | 20 | 5 | 11.1 | 1.80 | 20 | 1.92 |
| pip-5.0.0.93 | 2 | 880 | 1 | 631.5 | 1.39 | 757 | 1.92 |

**Per-stage p50 (ms) and speedup vs the baseline** (> 1 = faster)

| threads | stage | cool | pip-5.0.0.93 | speedup_cool |
|---|---|---|---|---|
| 1 | block_features | 1.678 | 1.676 | 1.00× |
| 1 | cvtColor_lab | 0.124 | 0.121 | 0.97× |
| 1 | frame_pipeline | 50.8 | 57.3 | 1.13× |
| 1 | imdecode | 1.083 | 1.069 | 0.99× |
| 1 | register_aliked_lightglue_magsac | 2064.7 | 2055.7 | 1.00× |
| 1 | register_orb_magsac | 38.5 | 44.6 | 1.16× |
| 1 | resize_area | 0.694 | 0.700 | 1.01× |
| 1 | ridge_predict | 0.022 | 0.022 | 1.00× |
| 1 | sobel_magnitude | 0.078 | 0.076 | 0.98× |
| 1 | warpPerspective | 1.426 | 1.411 | 0.99× |
| 2 | block_features | 1.679 | 1.668 | 0.99× |
| 2 | cvtColor_lab | 0.124 | 0.121 | 0.97× |
| 2 | frame_pipeline | 34.9 | 42.2 | 1.21× |
| 2 | imdecode | 1.084 | 1.070 | 0.99× |
| 2 | register_aliked_lightglue_magsac | 1160.4 | 1159.7 | 1.00× |
| 2 | register_orb_magsac | 23.1 | 28.0 | 1.21× |
| 2 | resize_area | 0.704 | 0.712 | 1.01× |
| 2 | ridge_predict | 0.023 | 0.022 | 0.99× |
| 2 | sobel_magnitude | 0.078 | 0.076 | 0.98× |
| 2 | warpPerspective | 0.782 | 0.772 | 0.99× |

**Fleet frames/s and speedup**

| threads | fleet | cool | pip-5.0.0.93 | speedup_cool |
|---|---|---|---|---|
| 1 | 20 | 1.03 | 1.03 | 1.00× |
| 1 | 880 | 0.80 | 0.79 | 1.00× |
| 2 | 20 | 1.82 | 1.80 | 1.01× |
| 2 | 880 | 1.40 | 1.39 | 1.01× |

**Amdahl: share of the summed stage time** (if every stage ran on every frame; ALIKED runs only when ORB fails)

| arm | threads | stage | share |
|---|---|---|---|
| cool | 2 | imdecode | 0.1 % |
| cool | 2 | register_orb_magsac | 1.8 % |
| cool | 2 | register_aliked_lightglue_magsac | 97.8 % |
| cool | 2 | warpPerspective | 0.1 % |
| cool | 2 | resize_area | 0.1 % |
| cool | 2 | cvtColor_lab | 0.0 % |
| cool | 2 | sobel_magnitude | 0.0 % |
| cool | 2 | block_features | 0.1 % |
| cool | 2 | ridge_predict | 0.0 % |
| pip-5.0.0.93 | 2 | imdecode | 0.1 % |
| pip-5.0.0.93 | 2 | register_orb_magsac | 2.2 % |
| pip-5.0.0.93 | 2 | register_aliked_lightglue_magsac | 97.4 % |
| pip-5.0.0.93 | 2 | warpPerspective | 0.1 % |
| pip-5.0.0.93 | 2 | resize_area | 0.1 % |
| pip-5.0.0.93 | 2 | cvtColor_lab | 0.0 % |
| pip-5.0.0.93 | 2 | sobel_magnitude | 0.0 % |
| pip-5.0.0.93 | 2 | block_features | 0.1 % |
| pip-5.0.0.93 | 2 | ridge_predict | 0.0 % |

**Output equivalence vs the baseline** (worst over the 20 frames)

| arm | stage | max_abs_diff | min_psnr_db | sites | shape_mismatch |
|---|---|---|---|---|---|
| cool | block_features | 0.0 | nan | 20 | False |
| cool | cvtColor_lab | 0.0 | inf | 20 | False |
| cool | imdecode | 0.0 | inf | 20 | False |
| cool | resize_area | 0.0 | inf | 20 | False |
| cool | sobel_magnitude | 0.0 | nan | 20 | False |
| cool | stage_fixedH | 0.0 | nan | 20 | False |
| cool | stage_pipeline | 0.00044201 | nan | 20 | False |
| cool | warpPerspective | 0.0 | inf | 20 | False |

**Cost**

| arm | cadence_min | instance | usd_per_h | fleet_frames_per_s | cameras_per_instance | usd_per_camera_month | break_even_speedup_vs_stock |
|---|---|---|---|---|---|---|---|
| cool | 15 | m9g.large | 0.10284 | 1.4029 | 1262 | 0.0586442 | 1.0511 |
| cool | 30 | m9g.large | 0.10284 | 1.4029 | 2525 | 0.0293221 | 1.0511 |
| pip-5.0.0.93 | 15 | m9g.large | 0.09784 | 1.3936 | 1254 | 0.0561653 | 1.0 |
| pip-5.0.0.93 | 30 | m9g.large | 0.09784 | 1.3936 | 2508 | 0.0280827 | 1.0 |

**Fleet scaling at a 30-minute cadence**

| arm | cadence_min | cameras | cycle_wall_s_one_instance | instances | usd_per_month |
|---|---|---|---|---|---|
| cool | 15 | 20 | 14.2562 | 1 | 74.0448 |
| cool | 15 | 100 | 71.2809 | 1 | 74.0448 |
| cool | 15 | 250 | 178.202 | 1 | 74.0448 |
| cool | 15 | 500 | 356.405 | 1 | 74.0448 |
| cool | 15 | 880 | 627.272 | 1 | 74.0448 |
| cool | 30 | 20 | 14.2562 | 1 | 74.0448 |
| cool | 30 | 100 | 71.2809 | 1 | 74.0448 |
| cool | 30 | 250 | 178.202 | 1 | 74.0448 |
| cool | 30 | 500 | 356.405 | 1 | 74.0448 |
| cool | 30 | 880 | 627.272 | 1 | 74.0448 |
| pip-5.0.0.93 | 15 | 20 | 14.3513 | 1 | 70.4448 |
| pip-5.0.0.93 | 15 | 100 | 71.7566 | 1 | 70.4448 |
| pip-5.0.0.93 | 15 | 250 | 179.392 | 1 | 70.4448 |
| pip-5.0.0.93 | 15 | 500 | 358.783 | 1 | 70.4448 |
| pip-5.0.0.93 | 15 | 880 | 631.458 | 1 | 70.4448 |
| pip-5.0.0.93 | 30 | 20 | 14.3513 | 1 | 70.4448 |
| pip-5.0.0.93 | 30 | 100 | 71.7566 | 1 | 70.4448 |
| pip-5.0.0.93 | 30 | 250 | 179.392 | 1 | 70.4448 |
| pip-5.0.0.93 | 30 | 500 | 358.783 | 1 | 70.4448 |
| pip-5.0.0.93 | 30 | 880 | 631.458 | 1 | 70.4448 |
<!-- END:cool:cool_g5_m9g_2026-10-24 -->

## Reproduce

```bash
python bench/make_pack.py                     # builds data/bench_pack (local frame cache; private, never committed)
python bench/cool_bench.py --out results/cool_bench/<run> --arm <label>     # one arm, this interpreter's cv2
python bench/compare_arms.py results/cool_bench/<run> --baseline pip-5.0.0.93
python bench/plot_amdahl.py results/cool_bench/<run>          # Amdahl chart
python bench/run_cool_bench.py --bucket <private bucket> --ami <COOL G5 AMI> --cool-price <USD/h>   # all of it on AWS
```
