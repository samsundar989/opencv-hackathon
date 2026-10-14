# SLICE 01 — Ingest, site selection, kill test

**Window:** Oct 13 (night) → Oct 14 (night). **Owner:** Claude Code. **Decides:** whether RiverSight proceeds as planned (D-0002).

## Goal
Prove on real data that camera frames carry enough signal to read stage to ±0.25 ft at many sites using only (a) frame registration, (b) a classical waterline detector along fixed transects, and (c) the projective pixel→stage model fitted from gauge history. No DNN, no AWS, no agent in this slice.

## Inputs already in the repo
- `src/riversight/data/{nims,nwis,join}.py` — verified API clients and the frame↔gauge join (tests pass).
- `src/riversight/geometry/projective.py` — robust 1-D projective fit + inverse + isotonic baseline (tests pass).
- `src/riversight/vision/{register,transect}.py` — ORB/ALIKED registration with USAC_MAGSAC; transect profiles + classical transition detector (tests pass on synthetic data; **untested on real frames** — expect to iterate).
- `docs/DATA_SOURCES.md` — endpoints/shapes.

## Steps
1. **Env:** `pip install -e ".[dev]"` in the global Python; `pytest` green; `.env` with `USGS_API_KEY` (ask Samuel in `docs/HUMAN.md` if missing; proceed without it at low rate).
2. **Catalog:** `riversight cameras --out data/cameras_all.csv --min-age-days 90` (expect ~830 gauged, active, ≥90-day cameras).
3. **Site selection (20 sites) → `data/sites/kill_test.yaml`.** For each candidate, pull 30 days of gauge stage (cheap) and compute `stage_variability`. Rank by `p95_p05_ft` (need signal: prefer ≥0.5 ft swing in 30 days), require ≥2 frames/day on average, and prefer medium/small rivers (camera descriptions with "Creek", "Ck", "Branch", "Rv at <bridge>"). Include **≥6 Texas sites** (e.g. `TX_Blanco_River_at_Wimberley`, `TX_San_Antonio_River_at_East_Nueva_St_in_San_Antonio`, `TX_Buffalo_Bayou_at_State_HWY_6_near_Addicks`, `TX_White_Rk_Ck_at_Greenville_Ave_Dallas`, `TX_Clear_Fk_Trinity_Rv_at_Ft_Worth`, `TX_Zacate_Creek_at_Jacaman_Road_Laredo`) and a geographic spread (WI, MN, NY, NJ, OH, CO). Write the reason per site in the YAML. **Look at 3 frames per site** (save a contact sheet `results/kill_test/contact_<site>.jpg`) and drop sites where no bank/structure is visible.
4. **Fetch:** `riversight fetch --site <camId> --days 30 --prefix 720` for the 20 sites (~20 × 30 × 24–48 frames ≈ 15–30k images at 720 px; ~1–3 GB). Run ≤4 downloads in parallel; cache under `data/raw/720/<camId>/`.
5. **Transects:** per site, define 3–5 transects in reference-image coordinates. Preferred: automatic — compute a temporal median frame and a "stage-correlated change" map (pixelwise correlation between gray intensity and gauge stage over the fit window); transects run from high-|corr| land pixels towards water perpendicular to the dominant waterline direction. Acceptable fallback for the kill test: hand-picked polylines via a tiny matplotlib click tool `scripts/transect_tool.py` (store in `data/sites/<camId>/transects.yaml`). Mask the USGS overlay text bands (top/bottom rows) in registration.
6. **Reference + registration:** reference = sharpest daytime frame near the median stage (Laplacian variance). Register every frame (ORB first; switch to ALIKED+LightGlue if the ONNX models are downloaded — see DATA_SOURCES §4). Record `score`, `n_inliers`, `reproj_err_px`. Registration success = `Registration.ok`.
7. **Waterline:** for each registered frame, warp into reference coords (`warp_to_reference`), run `profile_features` + `detect_transition` per transect with the previous frame's position as prior. Store `s_k`, `conf_k`.
8. **Fit + evaluate (temporal split):** first 20 days = fit, last 10 days = test. Per transect fit `fit_robust(h, s)`; per frame invert each transect's s → h, fuse by confidence-weighted median; compare with gauge. Also fit the **isotonic lookup** baseline and a **persistence** baseline (last gauge value before the frame, as if the gauge went silent 24 h earlier).
9. **Report:** `results/kill_test/summary.csv` (site, n_frames, reg_rate, coverage, MAE_ft, RMSE_ft, pct_within_0.1, pct_within_0.25, px_per_ft, stage_range_ft, baseline MAEs) and `results/kill_test.md` with a per-site table, 2 example overlays per site (frame + transects + detected waterline + predicted vs gauge), and a plain-English verdict. Commit results.

## Acceptance (PASS/FAIL is binary; no partial credit)
- Registration success ≥90% of frames across the 20 sites (daytime frames; night frames excluded and counted separately).
- **MAE ≤ 0.25 ft on the 10 test days at ≥10 of 20 sites** with the projective model.
- Projective model beats persistence-24h at those sites.
- `results/kill_test.md` committed with the numbers and overlays; `docs/STATUS.md` updated; `D-0002` written in `docs/DECISIONS.md` as PASS or FAIL with the table.

## If FAIL
Do not tune into the test window. Write the failure modes (per site: no visible bank, wide river/px-per-ft too low, registration drift, detector picks wrong edge) in `results/kill_test.md`, then stop and raise `Q-0001` in `docs/HUMAN.md` with your recommendation: (a) proceed anyway on the subset of sites that pass, (b) reframe as rise/ice/obstruction event detection, (c) switch to Porter (see `docs/research/ideas.md`). Cowork and Samuel decide.

## Ship-with-less line
If time is short: 12 sites, ORB only, hand-drawn transects, 20 days. The acceptance thresholds do not change.
