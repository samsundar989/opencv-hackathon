"""SLICE_01B step 4: score the frozen test days ONCE under protocol v2 (D-0006) with the D-0007 setting.

Guards (refuses to run otherwise):
  * results/scene/frozen_config.json exists and its sha256 is recorded in results/constants.sha256;
  * results/kill_test_v2.csv does not exist yet (scored exactly once — no re-runs, D-0006).

Per site: extract features of the registered daylight test frames (Oct 4 00Z – Oct 14 00Z, SLICE_01
registration cache, same reference) → train the final model on all calibration frames (< Oct 3 00Z) with the
frozen setting → predict → smooth (causal) → σ from the setting's forward-chaining out-of-fold residuals
→ protocol v2 metrics → verdict. A site without a model counts as failing.

Outputs: results/kill_test_v2.csv, results/kill_test_v2.md, results/kill_test_v2/<cam>_ts.png,
results/kill_test_v2/<cam>_floodheight.png, results/kill_test_v2/<cam>_pred.csv,
data/derived/<cam>/final_model.npz (flood-height map + predictions; for the demo assets).

  workerq submit ... -- python scripts/scene_score.py --jobs 4
"""
from __future__ import annotations

import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse
import hashlib
import json
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
DATA = Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))
RES = ROOT / "results"
FROZEN = RES / "scene" / "frozen_config.json"
OUT_CSV = RES / "kill_test_v2.csv"
TEST_START, TEST_END = pd.Timestamp("2026-10-04", tz="UTC"), pd.Timestamp("2026-10-14", tz="UTC")


def check_guards():
    if OUT_CSV.exists():
        sys.exit(f"refusing: {OUT_CSV} exists — the frozen test days are scored exactly once (D-0006)")
    if not FROZEN.exists():
        sys.exit("refusing: no frozen config (D-0007) yet")
    digest = hashlib.sha256(FROZEN.read_bytes().replace(b"\r\n", b"\n")).hexdigest()   # git checkout may add CRLF
    hashes = (RES / "constants.sha256").read_text(encoding="utf-8") if (RES / "constants.sha256").exists() else ""
    if digest not in hashes:
        sys.exit(f"refusing: sha256 {digest} of frozen_config.json is not in results/constants.sha256")
    return json.loads(FROZEN.read_text(encoding="utf-8"))


def tier_of(cam: str, cfg: dict, reg_rate: float, cv_rho: float, cal_days: float) -> str:
    if cam in cfg["tier_a"]:
        return "A"
    if reg_rate < cfg["tier_c_reg_rate"] or not np.isfinite(cv_rho) or cv_rho < cfg["tier_c_cv_spearman"] \
            or cal_days < cfg["tier_c_min_days"]:
        return "C"
    return "B"


def score_site(cam: str, cfg: dict, window: str = "test", out_dir: Path | None = None) -> dict:
    import cv2
    cv2.setNumThreads(1)
    import scene_features
    from scene_tune import gauge_series, load_train
    from riversight.calib.flood_height_map import fit_thr
    from riversight.calib.scene_regressor import causal_median, kalman_1d, kalman_params
    from riversight.eval import protocol_v2 as pv
    from riversight.killtest import Cfg, register_site
    from riversight.vision.scene_features import grid_for, pool_blocks
    from riversight import viz

    out_dir = out_dir or (RES / "kill_test_v2")
    out_dir.mkdir(parents=True, exist_ok=True)
    # registration rate on the test days (daylight frames), from the SLICE_01 cache
    doc = yaml.safe_load((DATA / "sites" / "kill_test.yaml").read_text(encoding="utf-8"))
    t1 = pd.Timestamp(doc["window"]["end"])
    t0 = t1 - pd.Timedelta(days=doc["window"]["days"])
    frames, stage, _, _, reg = register_site(cam, DATA, t0, t0 + pd.Timedelta(days=doc["window"]["fit_days"]), t1, Cfg())
    day = reg.join(frames["window"])
    day = day[(day["window"] == window) & ~day["night"].astype(bool)]
    reg_ok, reg_n = int(day["ok"].sum()), int(len(day))
    scene_features.run(cam, "kill30", window)
    z = np.load(DATA / "derived" / cam / f"scene_kill30_{window}.npz")
    t_te = pd.to_datetime(z["t"], utc=True)
    h_te = z["h"].astype(float)
    g_full = pd.Series(stage["value"].to_numpy(float), index=pd.DatetimeIndex(stage["time"]))
    hist_g = gauge_series(cam)
    gauge = pd.concat([hist_g, g_full]).sort_index()
    gauge = gauge[~gauge.index.duplicated(keep="last")]

    L = load_train(cam)
    bs, thr, lam, smooth = cfg["bs"], cfg["thr"], cfg["lam"], cfg["smooth"]
    cam_pred = np.full(len(h_te), np.nan)
    sigma, cv_rho, n_roi, cal_days, cal_h = np.nan, np.nan, 0, 0.0, np.array([np.nan])
    M = None
    if L is not None and len(L[0]) >= 200 and len(h_te):
        t_tr, h_tr, F_tr = L
        cal_days, cal_h = (t_tr[-1] - t_tr[0]).days, h_tr
        Xtr = F_tr.astype(np.float32)
        Xte = z["F"].astype(np.float32)
        if bs == 8:
            Xtr, Xte = pool_blocks(Xtr), pool_blocks(Xte)
        M = fit_thr(Xtr, h_tr)
        roi = M.acc >= thr
        if roi.sum() < cfg["min_roi"]:
            roi = np.ones_like(roi)
        n_roi = int(roi.sum())
        from scene_tune import _eig_ridge
        solve = _eig_ridge(Xtr[:, roi].reshape(len(Xtr), -1), Xte[:, roi].reshape(len(Xte), -1), h_tr)
        raw, loo = solve(lam)
        if smooth == "kalman":
            q, _ = kalman_params(hist_g.index, hist_g.values, np.zeros(4))
            rho = np.corrcoef(loo[:-1], loo[1:])[0, 1]
            r = max(float(np.var(loo)) * (1 - np.clip(rho, 0, 0.95)), 1e-6)
            cam_pred = kalman_1d(t_te, raw, q, r)[0]
        else:
            cam_pred = causal_median(t_te, raw, "3h")
        cv = np.load(DATA / "derived" / cam / "tune_cv.npz") if (DATA / "derived" / cam / "tune_cv.npz").exists() else None
        if cv is not None:
            key = f"{bs}|{thr}|{lam}|{smooth}"
            k = list(cv["keys"]).index(key)
            oof, hh = cv["P"][k], cv["h"]
            ok = np.isfinite(oof)
            if ok.sum() > 5:
                sigma = float(np.std(oof[ok] - hh[ok]))
                cv_rho = float(pd.Series(oof[ok]).corr(pd.Series(hh[ok]), method="spearman"))
        grid = grid_for(len(M.acc))
        lo, hi = np.quantile(h_tr, 0.04), np.quantile(h_tr, 0.96)
        np.savez_compressed((DATA / "derived" / cam / "final_model.npz") if window == "test" else (out_dir / f"{cam}_final_model.npz"), acc=M.acc, thr=M.thr, grid=np.array(grid),
                            roi=roi, lo=lo, hi=hi, t=t_te.asi8, h=h_te, pred=cam_pred, sigma=sigma,
                            filename=z["filename"], min_acc=thr)
        fh = viz.floodheight_colour(M.thr, M.acc, grid, lo, hi, thr)
        cv2.imwrite(str(out_dir / f"{cam}_floodheight.png"), np.hstack([fh, viz.legend_bar(lo, hi, fh.shape[0])]))

    reg_rate = reg_ok / reg_n if reg_n else float("nan")
    tier = tier_of(cam, cfg, reg_rate, cv_rho, cal_days)
    r = pv.site_metrics(t_te, cam_pred, h_te, gauge, cal_h, reg_rate, tier) if len(h_te) else \
        {"tier": tier, "n": 0, "p1": False, "has_events": False, "p2": None, "mae": np.nan}
    r.update(cam_id=cam, reg_ok=reg_ok, reg_n=reg_n, sigma=sigma, cv_spearman=cv_rho, n_roi=n_roi,
             cal_frames=0 if L is None else len(L[0]), cal_days=cal_days)
    if len(h_te):
        p24 = pv.last_known(t_te, gauge, "24h")
        ev = np.isfinite(p24) & (np.abs(h_te - p24) >= pv.EVENT_FT)
        cv2.imwrite(str(out_dir / f"{cam}_ts.png"),
                    viz.timeseries_png(g_full, t_te, cam_pred, sigma, ev, f"{cam}  MAE {r['mae']:.2f} ft  tier {tier}"))
        pd.DataFrame({"time": t_te, "gauge_ft": h_te, "camera_ft": cam_pred, "sigma_ft": sigma, "event": ev}) \
            .to_csv(out_dir / f"{cam}_pred.csv", index=False, float_format="%.4f")
    return r


def p2_history(cams: list[str], cfg: dict) -> dict:
    """P2 on the last 30 days of history via forward-chaining CV (only reported if < 5 test-event sites)."""
    from scene_tune import CUT, gauge_series
    from riversight.eval import protocol_v2 as pv
    key = f"{cfg['bs']}|{cfg['thr']}|{cfg['lam']}|{cfg['smooth']}"
    n_ev, n_win = 0, 0
    for cam in cams:
        p = DATA / "derived" / cam / "tune_cv.npz"
        if not p.exists():
            continue
        z = np.load(p)
        t = pd.to_datetime(z["t"], utc=True)
        oof = z["P"][list(z["keys"]).index(key)]
        m = (t >= CUT - pd.Timedelta("30D")) & np.isfinite(oof)
        if m.sum() < 5:
            continue
        p24 = pv.last_known(t[m], gauge_series(cam), "24h")
        ev = np.isfinite(p24) & (np.abs(z["h"][m] - p24) >= pv.EVENT_FT)
        if ev.sum() >= pv.MIN_EVENT_FRAMES:
            n_ev += 1
            n_win += int(np.mean(np.abs(oof[m][ev] - z["h"][m][ev])) < np.mean(np.abs(p24[ev] - z["h"][m][ev])))
    return {"event_sites": n_ev, "camera_wins": n_win, "frac": n_win / n_ev if n_ev else float("nan")}


def write_report(df: pd.DataFrame, v: dict, cfg: dict, p2h: dict | None):
    f = lambda x, d=2: "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else (f"{x:.{d}f}" if isinstance(x, float) else str(x))
    lines = [
        "# Kill test v2 — frozen test days scored once (protocol v2, D-0006; setting D-0007)", "",
        f"**Verdict: {v['verdict']}** — P1 {v['P1_sites']}/{v['n_sites']} sites (need ≥ 10) · "
        f"P2 {v['P2_sites']}/{v['P2_event_sites']} event sites (need ≥ 70 %) · P3 registration {v['reg_rate']:.3f} (need ≥ 0.90).", "",
        f"Test days: {TEST_START:%Y-%m-%d %H}Z – {TEST_END:%Y-%m-%d %H}Z, daylight registered frames, 20 sites of "
        "`data/sites/kill_test.yaml`. Calibration: all frames before 2026-10-03 00Z (history + SLICE_01 fit window). "
        f"Setting (D-0007, hash in `results/constants.sha256`): block {cfg['bs']} px, ROI reliability ≥ {cfg['thr']}, "
        f"ridge λ {cfg['lam']}, smoothing {cfg['smooth']}. Produced by `scripts/scene_score.py`; per-site numbers in "
        "`results/kill_test_v2.csv`.", "",
        "P3 is computed over the 30-day window's daylight frames, as in SLICE_01 (95.7 %); the test-day rate per site is in the table.", "",
    ]
    if p2h is not None:
        lines += [f"Fewer than 5 sites had test-window events, so P2 is also reported on the last 30 days of history "
                  f"(forward-chaining CV, labelled, not the frozen test): camera beats 24 h last-known value at "
                  f"{p2h['camera_wins']}/{p2h['event_sites']} event sites.", ""]
    lines += ["## Per-site results (ft)", "",
              "| site | tier | n | reg (test) | MAE | nMAE | P1 | ev frames | MAE ev / LKV-24h ev | P2 | 15 min pers. | 24 h pers. | const | ρ | flood bacc (cam / 24h) | σ |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in df.iterrows():
        lines.append(f"| {r['cam_id']} | {r['tier']} | {r['n']} | {f(r.get('reg_rate'))} | {f(r.get('mae'))} | {f(r.get('nmae'))} | "
                     f"{'✔' if r['p1'] else '✘'} | {r.get('n_ev', 0)} | {f(r.get('mae_ev'))} / {f(r.get('mae_p24_ev'))} | "
                     f"{'—' if r.get('p2') is None or (isinstance(r.get('p2'), float) and np.isnan(r.get('p2'))) else ('✔' if r['p2'] else '✘')} | "
                     f"{f(r.get('mae_p15'))} | {f(r.get('mae_p24'))} | {f(r.get('mae_const'))} | {f(r.get('spearman'))} | "
                     f"{f(r.get('bacc_flood'))} / {f(r.get('bacc_flood_p24'))} | {f(r.get('sigma'))} |")
    lines += ["", "## Outage gap-fill: camera vs last-known value (MAE ft, all scored frames)", "",
              "| site | 6 h LKV / cam | 24 h LKV / cam | 72 h LKV / cam | 7 d LKV / cam |", "|---|---|---|---|---|"]
    for _, r in df.iterrows():
        lines.append(f"| {r['cam_id']} | " + " | ".join(f"{f(r.get(f'gap_{k}_lkv'))} / {f(r.get(f'gap_{k}_cam'))}" for k in ("6h", "24h", "72h", "7d")) + " |")
    lines += ["", "## Plots", "", "Per site: `results/kill_test_v2/<cam>_ts.png` (camera ± σ vs gauge, event frames shaded) and "
              "`results/kill_test_v2/<cam>_floodheight.png` (h* per block; grey = not reliable).", ""]
    for _, r in df.iterrows():
        if (RES / "kill_test_v2" / f"{r['cam_id']}_ts.png").exists():
            lines += [f"### {r['cam_id']}", "", f"![ts](kill_test_v2/{r['cam_id']}_ts.png)", "",
                      f"![h*](kill_test_v2/{r['cam_id']}_floodheight.png)", ""]
    (RES / "kill_test_v2.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", type=Path, default=DATA / "sites" / "kill_test.yaml")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--dry-run", type=Path, metavar="DIR",
                    help="code-path check on the FIT window (leaky, meaningless numbers) with a candidate config; "
                         "writes only to DIR, never touches the test days or results/")
    ap.add_argument("--config", type=Path, help="dry-run only: config json")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    cams = [s["cam_id"] for s in yaml.safe_load(a.sites.read_text(encoding="utf-8"))["sites"] if not a.only or s["cam_id"] in a.only]
    if a.dry_run:
        cfg = json.loads(a.config.read_text(encoding="utf-8"))
        a.dry_run.mkdir(parents=True, exist_ok=True)
        rows = [score_site(c, cfg, "fit", a.dry_run) for c in cams]
        pd.DataFrame(rows).to_csv(a.dry_run / "dryrun.csv", index=False)
        print(pd.DataFrame(rows)[["cam_id", "n", "mae", "tier", "p1", "n_ev", "p2"]].to_string())
        return
    cfg = check_guards()
    rows = []
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(score_site, c, cfg): c for c in cams}
        for k, fu in enumerate(as_completed(futs), 1):
            p = os.environ.get("WORKERQ_PROGRESS")
            if p:
                Path(p).write_text(f"{k / len(cams):.4f}")
            try:
                rows.append(fu.result())
                print(f"{futs[fu]}: MAE {rows[-1].get('mae')}", flush=True)
            except Exception:
                print(f"{futs[fu]}: ERROR\n{traceback.format_exc()}", flush=True)
                rows.append({"cam_id": futs[fu], "tier": "C", "n": 0, "p1": False, "has_events": False, "p2": None,
                             "mae": np.nan, "error": "exception (see job log)"})
    df = pd.DataFrame(rows).set_index("cam_id").loc[cams].reset_index()
    # P3 as pre-registered: 30-day daylight registration (SLICE_01 summary)
    reg = pd.read_csv(RES / "kill_test" / "registration_summary.csv")
    reg_rate = float(reg["registered"].sum() / reg["day"].sum())
    v = pv_verdict(df, reg_rate)
    p2h = p2_history(cams, cfg) if v["P2_needs_history_cv"] else None
    df.round(4).to_csv(OUT_CSV, index=False)
    (RES / "kill_test_v2_verdict.json").write_text(json.dumps({**v, "p2_history": p2h, "config": cfg}, indent=2, default=str))
    write_report(df, v, cfg, p2h)
    print(json.dumps(v, indent=2, default=str))


def pv_verdict(df, reg_rate):
    from riversight.eval import protocol_v2 as pv
    return pv.verdict(df, reg_rate)


if __name__ == "__main__":
    main()
