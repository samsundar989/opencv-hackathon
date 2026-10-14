# SLICE 02 — Registration bank, transect tool, stage model v1 (30–60 sites)

**Window:** Oct 15–16. **Depends on:** SLICE_01 PASS.

## Goal
Scale the kill-test pipeline to 30–60 sites × 60–90 days with proper OpenCV-5 registration and a per-site reference bank; produce the first fleet-wide MAE table and the ORB-vs-ALIKED ablation.

## Deliverables
1. `models/` download script with SHA256 manifest for ALIKED + LightGlue ONNX (and YuNet); `Registrar` uses ALIKED+LightGlue by default, ORB as `--features orb` ablation.
2. **Reference bank:** per site, 2–6 references (dawn/day/dusk, dry/wet season) selected by clustering a cheap global descriptor (color histogram + DINOv2/SigLIP embedding if cheap via cv2.dnn) and stored in `cv2.ANNIndex` (OpenCV 5 `features` module) for nearest-reference lookup at inference. Document in `docs/OPENCV5_USAGE.md`.
3. **Transects:** automatic proposal (stage-correlated change map) + review tool; `data/sites/<camId>/transects.yaml` committed for all sites.
4. **Stage model v1:** per-transect projective fit with uncertainty (`sigma_h` from waterline confidence), transect fusion, extrapolation flag when outside `[h_min, h_max]`, CUSUM residual tracking vs gauge → `CAMERA_MOVED`, `LOW_CONF`, `GAUGE_SUSPECT`, `RISING` flags (thresholds in `src/riversight/config.py`, all in `constants.py` to be frozen in SLICE_04).
5. **Fleet table:** `results/fleet_v1/summary.csv` + `results/fleet_v1.md`: per site MAE/RMSE/coverage/px-per-ft, temporal split; ORB vs ALIKED registration rate and MAE; isotonic vs projective; persistence baseline.
6. `riversight run-site --site <camId> --from --to` and `riversight run-fleet --sites data/sites/fleet.yaml` CLIs; one frame/site processing time logged (this is the number COOL will later accelerate).

## Acceptance
- ≥30 sites processed; registration (ALIKED) ≥92% of daytime frames; median site MAE ≤0.2 ft; ablation table committed; `docs/OPENCV5_USAGE.md` lists every OpenCV 5 call used with "why" and "without it".
- Per-frame CPU time on the Windows box ≤0.5 s at 720 px (so one c8g.large can cover ~900 sites every 15 min).

## Ship-with-less
30 sites, 45 days, ORB fallback allowed on sites where ALIKED fails to load, but report it.
