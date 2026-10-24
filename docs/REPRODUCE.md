# Reproduce RiverSight's results

Three levels, from "check every number in five minutes" to "rebuild the data from USGS". Times are measured, not estimated: `report/time_fresh_clone.py` writes `results/repro/fresh_clone_times.json`.

## Level 1: fresh clone → tests → every reported number re-derived (no data download)

Python ≥ 3.12. OpenCV is pinned to `opencv-python-headless==5.0.0.93`.

On Windows, clone into a short folder or run `git config --global core.longpaths true` first: a few result filenames are long, and a deep clone path exceeds Windows' 260-character limit.

```bash
git clone <repo-url> riversight && cd riversight
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
python report/summarize_results.py                  # fleet summary from the frozen per-site results
python report/build_report_tables.py                # every table in report/REPORT.md
python scripts/check_report_numbers.py              # every number in README/REPORT/docs traced to results/
python report/verify_frozen.py                      # frozen config + scoring modules match results/constants.sha256
git diff --exit-code results report                 # re-derived files are byte-identical to the committed ones
```

Measured on the dev box (Windows 11, Python 3.14, commit recorded in the JSON): **70.1 s** end to end. The clone takes 1.5 s, the venv 4.7 s, `pip install` 53.1 s, `pytest` 8.9 s, and the re-derivation and check steps about 2 s together. The final `git diff` is empty.

What this proves: every headline number and every report table is computed by committed code from committed per-site predictions (`results/kill_test_v2/<cam>_pred.csv`) and summaries. Tests also check that the summary agrees with the frozen verdict JSON (`tests/w3/`).

What it does not redo: the test-day scoring itself. `scripts/scene_score.py` refuses to run a second time (the test days were read once, D-0002). Its frozen config and scoring modules are hashed in `results/constants.sha256`. `python report/verify_frozen.py` checks each hashed file, both the version committed with the hash file and the working copy (part of the timed run above).

## Level 2: with the local frame cache

These steps need USGS frames, which we do not redistribute (`docs/RESPONSIBLE_USE.md`). Rebuild the cache from USGS with the polite fetchers: sequential, paced NIMS listing calls, at most four parallel downloads, everything cached under `data/raw/`. Put a free USGS API key in `.env` first.

```bash
python scripts/fetch_sites.py                       # 30-day kill-test window, 20 sites
python scripts/fetch_history.py                     # 12-month calibration history (slow by design)
python scripts/scene_features.py --source history   # registered block features (heavy: run through a job queue)
python scripts/scene_features.py --source kill30 --window fit
```

Then:

| step | command | output |
|---|---|---|
| bootstrap CIs and coverage | `python report/bootstrap_coverage.py` | `results/kill_test_v2_ci.csv`, `coverage_v2.csv`, `kill_test_v2_ci_summary.json` |
| Hancock head-to-head | `python report/headtohead_hancock.py` | `results/headtohead_hancock/` |
| COOL bench input pack | `python bench/make_pack.py` | `data/bench_pack/` (private) |
| one bench arm, locally | `python bench/cool_bench.py --out results/cool_bench/<run> --arm <label>` | `results/cool_bench/<run>/<label>/` |
| a dry run of the scorer on the fit window | `python scripts/scene_score.py --dry-run <dir> --config results/scene/frozen_config.json` | writes only to `<dir>`; never touches the test days |

## Level 3: AWS

- **COOL benchmark:** `python bench/run_cool_bench.py --bucket <private bucket> --ami <COOL G5 AMI> --cool-price <USD/h>` launches one Graviton instance, runs both arms, fetches the results and terminates it (`docs/COOL_BENCHMARK.md`).
- **Live deployment:** `docs/DEPLOY.md` (W1; in progress).
