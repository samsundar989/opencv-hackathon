# RiverSight

**Every public river webcam becomes a self-checking water-level gauge.**
Entry for the OpenCV AI Competition 2026, powered by AWS.

RiverSight turns the ~880 public USGS HIVIS river webcams that sit next to an official stream gauge into independent, self-calibrating water-level instruments — using OpenCV 5 (ALIKED + LightGlue registration, USAC_MAGSAC, new DNN engine) on AWS Graviton with COOL — and runs a fleet agent that keeps the cameras honest and escalates fast-rising water to a human.

- Plan of record: `docs/PLAN_2026-10-13_RIVERSIGHT.md`
- Builder rules: `CLAUDE.md`
- Data sources (verified endpoints): `docs/DATA_SOURCES.md`
- Status / decisions / questions: `docs/STATUS.md`, `docs/DECISIONS.md`, `docs/HUMAN.md`

## Quick start (local)
```bash
pip install -e ".[dev]"
cp .env.example .env            # add USGS_API_KEY
riversight cameras --active --gauged --min-age-days 90 --state TX
riversight fetch --site TX_Guadalupe_Rv_at_Comfort --days 30
riversight kill-test --sites data/sites/kill_test.yaml --days 30
pytest
```

Prior art and what is new here: `docs/research/prior-art.md`. We do not claim to be the first camera-based water-level system; we claim the first open, fleet-wide, survey-free, self-calibrating one with a held-out-site benchmark and a live endpoint.
