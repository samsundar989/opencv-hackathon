"""Bootstrap CIs and coverage for the frozen kill test v2 (W3, SPRINT_W3 §4b items 2-3).

Reads only the frozen per-site predictions (`results/kill_test_v2/<cam>_pred.csv`, never edited) and the
local frame index (`data/raw/720/<cam>/`) and writes:

  results/kill_test_v2_ci.csv        per site: MAE, RMSE, bias with day-block bootstrap 95% CIs, P1 pass rate
  results/coverage_v2.csv            per site: test-window hours / daylight hours / frames with a stage estimate
  results/kill_test_v2_ci_summary.json  fleet: median MAE CI, P1 count interval, camera-hours of stage per day

Block bootstrap: resample the site's test days (UTC) with replacement, B = 2000, seed 20261015. The fleet
median-MAE interval resamples days independently within every site and takes the median across sites.

Coverage: an hour counts as covered when at least one frame in it got a stage estimate. Daylight = sun
elevation ≥ −3° at the middle of the hour (the SLICE_01 night threshold, `KillTestConfig.night_sun_elev`).

    python report/bootstrap_coverage.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from riversight.killtest import sun_elevation_deg  # noqa: E402

RES = ROOT / "results"
B = 2000
SEED = 20261015
TEST_START = pd.Timestamp("2026-10-04T00:00:00Z")
TEST_END = pd.Timestamp("2026-10-14T00:00:00Z")
NIGHT_ELEV = -3.0
MAE_FT, NMAE = 0.25, 0.10   # protocol v2 P1 (D-0006)


def day_bootstrap(err: np.ndarray, days: np.ndarray, rng: np.random.Generator, b: int = B) -> np.ndarray:
    """(b, 3) bootstrap replicates of (MAE, RMSE, bias) resampling whole days."""
    ud = np.unique(days)
    groups = [err[days == d] for d in ud]
    out = np.empty((b, 3))
    for i in range(b):
        e = np.concatenate([groups[j] for j in rng.integers(0, len(ud), len(ud))])
        out[i] = (np.abs(e).mean(), np.sqrt((e ** 2).mean()), e.mean())
    return out


def frame_time(p: Path) -> pd.Timestamp:
    d, t = p.stem.split("___")[1].split("T")
    return pd.Timestamp(f"{d}T{t.replace('-', ':')}")


def site_latlon() -> dict[str, tuple[float, float]]:
    y = yaml.safe_load((ROOT / "data" / "sites" / "kill_test.yaml").read_text(encoding="utf-8"))
    return {s["cam_id"]: (float(s["lat"]), float(s["lng"])) for s in y["sites"]}


def coverage(cam: str, pred_times: pd.DatetimeIndex, lat: float, lon: float) -> dict:
    hours = pd.date_range(TEST_START, TEST_END, freq="1h", inclusive="left")
    day_h = sun_elevation_deg(lat, lon, pd.Series(hours + pd.Timedelta(minutes=30))) >= NIGHT_ELEV
    files = sorted((ROOT / "data" / "raw" / "720" / cam).glob("*.jpg"))
    ft = pd.DatetimeIndex([frame_time(f) for f in files]).tz_convert("UTC") if files else pd.DatetimeIndex([], tz="UTC")
    ft = ft[(ft >= TEST_START) & (ft < TEST_END)]
    f_day = sun_elevation_deg(lat, lon, pd.Series(ft)) >= NIGHT_ELEV if len(ft) else np.zeros(0, bool)
    est_h = set(pred_times.floor("1h"))
    cov = np.array([h in est_h for h in hours])
    return {
        "cam_id": cam, "hours": len(hours), "daylight_hours": int(day_h.sum()),
        "hours_with_estimate": int(cov.sum()),
        "pct_hours": 100 * cov.mean(), "pct_daylight_hours": 100 * cov[day_h].mean() if day_h.any() else np.nan,
        "frames_listed": len(ft), "daylight_frames_listed": int(f_day.sum()), "frames_with_estimate": len(pred_times),
        "pct_frames": 100 * len(pred_times) / len(ft) if len(ft) else np.nan,
        "pct_daylight_frames": 100 * len(pred_times) / f_day.sum() if f_day.sum() else np.nan,
        "camera_hours_per_day": cov.sum() / ((TEST_END - TEST_START) / pd.Timedelta(days=1)),
    }


def main() -> None:
    kt = pd.read_csv(RES / "kill_test_v2.csv").set_index("cam_id")
    ll = site_latlon()
    rng = np.random.default_rng(SEED)
    rows, crow, per_site_err = [], [], {}
    for cam in kt.index:
        p = pd.read_csv(RES / "kill_test_v2" / f"{cam}_pred.csv", parse_dates=["time"])
        p = p[np.isfinite(p.camera_ft) & np.isfinite(p.gauge_ft)]
        err = (p.camera_ft - p.gauge_ft).to_numpy()
        days = p.time.dt.tz_convert("UTC").dt.floor("1D").astype("int64").to_numpy()
        mae = np.abs(err).mean()
        if abs(round(mae, 4) - kt.loc[cam, "mae"]) > 6e-4:
            raise SystemExit(f"{cam}: MAE {mae:.4f} from pred.csv != {kt.loc[cam, 'mae']} in kill_test_v2.csv")
        rng_ft = kt.loc[cam, "calib_p5_p95_ft"]
        bs = day_bootstrap(err, days, rng)
        p1 = (bs[:, 0] <= MAE_FT) | (bs[:, 0] / rng_ft <= NMAE)
        lo, hi = np.percentile(bs, [2.5, 97.5], axis=0)
        rows.append({"cam_id": cam, "tier": kt.loc[cam, "tier"], "n": len(err), "n_days": len(np.unique(days)),
                     "mae": mae, "mae_lo": lo[0], "mae_hi": hi[0],
                     "rmse": np.sqrt((err ** 2).mean()), "rmse_lo": lo[1], "rmse_hi": hi[1],
                     "bias": err.mean(), "bias_lo": lo[2], "bias_hi": hi[2],
                     "p1": bool(kt.loc[cam, "p1"]), "p1_boot_rate": p1.mean()})
        per_site_err[cam] = (err, days, rng_ft)
        crow.append(coverage(cam, pd.DatetimeIndex(p.time).tz_convert("UTC"), *ll[cam]))

    # fleet: median MAE and P1 count under joint resampling (independent day draws per site)
    med, p1n = np.empty(B), np.empty(B, int)
    groups = {c: [e[d == u] for u in np.unique(d)] for c, (e, d, _) in per_site_err.items()}
    for i in range(B):
        maes, n1 = [], 0
        for c, g in groups.items():
            e = np.concatenate([g[j] for j in rng.integers(0, len(g), len(g))])
            m = np.abs(e).mean()
            maes.append(m)
            n1 += (m <= MAE_FT) or (m / per_site_err[c][2] <= NMAE)
        med[i], p1n[i] = np.median(maes), n1

    ci = pd.DataFrame(rows)
    cov = pd.DataFrame(crow)
    ci.to_csv(RES / "kill_test_v2_ci.csv", index=False, float_format="%.4f")
    cov.to_csv(RES / "coverage_v2.csv", index=False, float_format="%.2f")
    summ = {
        "bootstrap": {"B": B, "seed": SEED, "block": "UTC day"},
        "median_mae_ft": round(float(np.median(ci.mae)), 3),
        "median_mae_ci95_ft": [round(float(x), 3) for x in np.percentile(med, [2.5, 97.5])],
        "p1_sites": int(ci.p1.sum()),
        "p1_sites_ci95": [int(x) for x in np.percentile(p1n, [2.5, 97.5])],
        "coverage": {
            "test_days": int((TEST_END - TEST_START) / pd.Timedelta(days=1)),
            "median_pct_hours": round(float(cov.pct_hours.median()), 1),
            "median_pct_daylight_hours": round(float(cov.pct_daylight_hours.median()), 1),
            "median_pct_daylight_frames": round(float(cov.pct_daylight_frames.median()), 1),
            "fleet_camera_hours_per_day": round(float(cov.camera_hours_per_day.sum()), 1),
            "fleet_daylight_hours_per_day": round(float(cov.daylight_hours.sum() / 10), 1),
        },
    }
    (RES / "kill_test_v2_ci_summary.json").write_text(json.dumps(summ, indent=2) + "\n", encoding="utf-8")
    print(ci[["cam_id", "mae", "mae_lo", "mae_hi", "rmse", "p1_boot_rate"]].to_string(index=False))
    print(cov[["cam_id", "pct_hours", "pct_daylight_hours", "pct_daylight_frames", "camera_hours_per_day"]].to_string(index=False))
    print(json.dumps(summ, indent=2))


if __name__ == "__main__":
    main()
