# Cowork scene-model experiment (2026-10-14) — reference for SLICE_01B

This is throwaway research code, run in a Linux container on CPU. **Do not import it.** Port it into `src/riversight/` (see SLICE_01B). Absolute paths inside the scripts point to the Cowork scratch area; change them before running.

| file | what it is |
|---|---|
| `decode_stage.py`, `stage_hourly.csv` | Hourly gauge stage (ft), Sep 14 – Oct 14 2026 UTC, for 17 sites. Built from the OGC API: the most populous `time_series_id`, median of readings within ±10 min of each hour. |
| `prep.py` | Selects hourly frames within ±10 min of the hour, applies a daylight filter (HSV V > 60 and S > 18 on the ¼-size thumbnail), registers with SIFT(4000, 960 px) + ratio 0.8 + `USAC_MAGSAC` 3 px to the frame nearest 2026-10-01 18:00Z, warps to 1280×720, then downsizes to 320×180. |
| `model.py` | Block features (4×4 blocks: L minus frame median, a, b, Sobel magnitude, L std); flood-height map (`fit_thr`: Fisher split over 24 stage quantiles, balanced-accuracy reliability; `predict_thr`: weighted wet/dry vote); kernel ridge; protocols `fit20`, `blocked4`, `lodo`; metrics. |
| `control.py` | Confound control: ridge on non-water blocks, on water blocks (flood-height ROI) and on the top 25% of the image. |
| `fhmap.py`, `plot.py` | Flood-height map visual and time-series plots. |
| `compare_fit20.csv` | Head-to-head with the worker's `results/kill_test/fit_window_cv.csv`, same protocol (first 20 days, blocked 4-fold). |
| `results_*.csv` | Per-site metrics. Columns: `*S_*` are smoothed (3 h causal median); `*_ev` are event frames (|Δ24h| ≥ 0.25 ft); `*_bacc` is flood-state balanced accuracy (stage > median + 0.5 ft). |
| `floodheight_maps.jpg`, `ts_*.png` | Visuals. |

## Headline numbers
- **fit20, scene ridge:** MAE ≤ 0.25 ft at 9/17 sites (classical transects: 1/20); beats constant median at 14/17; beats 24 h persistence on event frames at 13/16. Median 0.25 ft (classical: 0.47 ft).
- **fit20, water-block ridge** (blocks the flood-height map marks as reliable): median 0.22 ft. Non-water blocks: 0.37 ft.
