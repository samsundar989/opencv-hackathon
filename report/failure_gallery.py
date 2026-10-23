"""Failure gallery (SPRINT_W3 §5): concrete cases with an image, the numbers and one paragraph each.

Images built from USGS frames are face-blurred with YuNet (`vision.privacy.blur_faces`, fails closed) and
downsized; plots are drawn with OpenCV. Numbers come from committed results files or are computed here and
written to results/failures/cases.json. The paragraphs live in results/failures/README.md (generated).

    python report/failure_gallery.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from riversight.live.quality import image_quality  # noqa: E402
from riversight.viz import timeseries_png  # noqa: E402
from riversight.vision.privacy import blur_faces  # noqa: E402

RES = ROOT / "results"
OUT = RES / "failures"
RAW = ROOT / "data" / "raw" / "720"
DER = ROOT / "data" / "derived"
TEST0, TEST1 = pd.Timestamp("2026-10-04", tz="UTC"), pd.Timestamp("2026-10-14", tz="UTC")
W = 640


def frame(cam: str, name: str) -> np.ndarray:
    img = cv2.imread(str(RAW / cam / name))
    if img is None:
        raise FileNotFoundError(name)
    img, _ = blur_faces(img)
    return cv2.resize(img, (W, int(img.shape[0] * W / img.shape[1])), interpolation=cv2.INTER_AREA)


def label(img: np.ndarray, text: str) -> np.ndarray:
    bar = np.full((30, img.shape[1], 3), 255, np.uint8)
    cv2.putText(bar, text, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (30, 30, 30), 1, cv2.LINE_AA)
    return np.vstack([bar, img])


def pair(a: np.ndarray, la: str, b: np.ndarray, lb: str) -> np.ndarray:
    a, b = label(a, la), label(b, lb)
    h = max(a.shape[0], b.shape[0])
    pad = lambda x: np.vstack([x, np.full((h - x.shape[0], x.shape[1], 3), 255, np.uint8)])  # noqa: E731
    return np.hstack([pad(a), np.full((h, 8, 3), 255, np.uint8), pad(b)])


def credit(img: np.ndarray) -> np.ndarray:
    bar = np.full((22, img.shape[1], 3), 255, np.uint8)
    cv2.putText(bar, "Images: USGS HIVIS (public domain); faces blurred (YuNet)", (8, 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (110, 110, 110), 1, cv2.LINE_AA)
    return np.vstack([img, bar])


def save(name: str, img: np.ndarray) -> str:
    p = OUT / name
    cv2.imwrite(str(p), img, [cv2.IMWRITE_JPEG_QUALITY, 85] if name.endswith(".jpg") else [])
    return f"results/failures/{name}"


def reg_table(cam: str) -> pd.DataFrame:
    r = pd.read_parquet(DER / cam / "registration_cascade.parquet")
    r["t"] = pd.to_datetime(r.filename.str.split("___").str[1].str.replace(".jpg", "", regex=False)
                            .str.replace(r"T(\d\d)-(\d\d)-(\d\d)", r"T\1:\2:\3", regex=True), utc=True)
    return r


def kt(cam: str) -> pd.Series:
    return pd.read_csv(RES / "kill_test_v2.csv").set_index("cam_id").loc[cam]


def line_chart(series: dict[str, pd.Series], title: str, ylab: str, size=(1000, 380)) -> np.ndarray:
    Wd, H = size
    L, R, T, B = 70, 220, 40, 45
    img = np.full((H, Wd, 3), 255, np.uint8)
    xs = sorted({x for s in series.values() for x in s.index})
    ymax = max(float(s.max()) for s in series.values()) * 1.1
    px = lambda i: int(L + (Wd - L - R) * i / max(len(xs) - 1, 1))  # noqa: E731
    py = lambda v: int(H - B - (H - T - B) * v / ymax)  # noqa: E731
    for v in np.linspace(0, ymax, 5):
        cv2.line(img, (L, py(v)), (Wd - R, py(v)), (230, 230, 230), 1)
        cv2.putText(img, f"{v:.2f}", (8, py(v) + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (90, 90, 90), 1, cv2.LINE_AA)
    for i, x in enumerate(xs):
        if i % 2 == 0:
            cv2.putText(img, x, (px(i) - 22, H - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (90, 90, 90), 1, cv2.LINE_AA)
    cols = [(180, 119, 31), (14, 127, 255), (44, 160, 44), (40, 39, 214), (189, 103, 148)]
    for k, (name, s) in enumerate(series.items()):
        c = cols[k % len(cols)]
        pts = [(px(xs.index(x)), py(v)) for x, v in s.items()]
        for a, b in zip(pts, pts[1:]):
            cv2.line(img, a, b, c, 2, cv2.LINE_AA)
        for p in pts:
            cv2.circle(img, p, 3, c, -1, cv2.LINE_AA)
        cv2.putText(img, name[:26], (Wd - R + 10, T + 20 + 22 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.42, c, 1, cv2.LINE_AA)
    cv2.putText(img, title, (L, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (30, 30, 30), 1, cv2.LINE_AA)
    cv2.putText(img, ylab, (Wd - R + 10, T + 20 + 22 * len(series)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (90, 90, 90), 1, cv2.LINE_AA)
    return img


def write_readme(c: dict) -> None:
    """results/failures/README.md: one paragraph per case, numbers interpolated from cases.json."""
    n, f, w, pe = c["night_ir"], c["fog_lens"], c["view_change_whiterock"], c["view_change_pecatonica"]
    te, ro, fm = c["diurnal_artifact_tenmile"], c["far_bank_rootriver"], c["tidal_firstmallard"]
    hk, sd = c["above_calibrated_range_hancock"], c["seasonal_drift"]
    img = lambda p: f"![]({Path(p).relative_to('results/failures').as_posix() if p.startswith('results/failures') else '../' + Path(p).relative_to('results').as_posix()})"  # noqa: E731
    md = f"""# Failure gallery

Generated by `report/failure_gallery.py`; every number is in `cases.json` or the results file named. Frames: USGS HIVIS, public domain, faces blurred with YuNet.

## 1. Night and IR frames are not scored

{img(n["image"])}

{100 * n["night_share_30d"]:.1f} % of all frames in the 30-day window ({n["night_frames_30d"]} of {n["frames_30d"]}) were taken with the sun below −3°. Many cameras switch to infrared at night: grey, differently lit and often noisier. The scene model's features (Lab colour and texture) are learned from daylight frames, so night frames get no reading, and the dashboard shows "night" instead of a number. At Hancock the IR frame still shows the staff plate clearly, which is where a plate reader has the advantage.

## 2. A hazy, wet lens on a high-flow day

{img(f["image"])}

Big Brook NJ. Sharpness (Laplacian variance) drops from {f["lap_good"]:.0f} to {f["lap_bad"]:.0f}, and the dark-channel fog score rises from {f["fog_good"]:.2f} to {f["fog_bad"]:.2f}. The frame still registered. The trouble is that turbid flood water and a fogged lens move the same metrics, so `LOW_QUALITY` can fire on exactly the frames where a reading matters most. The agent therefore checks registration and the gauge trend before discarding a frame. Big Brook registered only {100 * f["test_reg_rate"]:.0f} % of its test-day daylight frames ({f["test_frames"]} scored).

## 3. The scene changed after a flood (White Rock Creek, Dallas)

{img(w["image"])}

A flood shortly before the test window moved sediment, logs and vegetation. {w["failed_daylight_test_frames"]} daylight test frames did not register to the calibration reference, test-day registration was {100 * w["test_reg_rate"]:.0f} %, and MAE was {w["mae_ft"]:.2f} ft (fails P1 and P2). The live system flags `VIEW_CHANGE`, and the agent quarantines the camera and opens a recalibration ticket.

## 4. Cameras get re-aimed (Pecatonica River)

{img(pe["image"])}

The calibration history has {pe["unlinked_segments"]} periods taken from a view that cannot be registered to the current reference. The one shown ({pe["segment_start"]} to {pe["segment_end"]}, {pe["segment_frames"]} frames) is tighter and lower. These frames are excluded from calibration. Across the fleet, {pe["sites_with_unlinked_segments"]} of 20 cameras have such periods, which is why view-change handling is a core agent job, not an extra.

## 5. The model learned the sun, not the water (Tenmile Creek)

{img(te["image"])}

The gauge spans {te["test_range_ft"]:.2f} ft over the scored test frames, mostly a slow recession, but the camera estimate rises and falls every day with the sun, low in the morning and high at midday. Spearman ρ is {te["spearman"]:.2f} and MAE {te["mae_ft"]:.2f} ft. Some blocks in the region of interest track illumination or shadow, which correlated with stage in the calibration data. Here a 15-minute-old gauge reading is off by {te["mae_p15"]:.3f} ft, and even a 6-hour-old one by {te["gap_6h_lkv"]:.3f} ft. Fixes for a later version: illumination-invariant features, and sun angle as a covariate.

## 6. A far bank with almost no signal (Root River)

{img(ro["image"])}

The waterline is far from the camera and a foot of stage moves it only a few pixels. Only {ro["n_roi"]} reliable blocks survive, σ is {ro["sigma_ft"]:.2f} ft, and the estimate sits above the gauge with a steady offset (MAE {ro["mae_ft"]:.2f} ft) while the river changes by only {ro["test_range_ft"]:.2f} ft. The reported σ is honest; the reading is not useful at this site's resolution.

## 7. Tides compress the range (First Mallard Branch)

{img(fm["image"])}

A tidal slough with a daily range of several feet ({fm["test_range_ft"]:.2f} ft over the test days). The camera follows the tide (ρ {fm["spearman"]:.2f}, MAE {fm["mae_ft"]:.2f} ft, passes P1 on nMAE), but it flattens the peaks and troughs, and low tide often falls at night. Gap-filling is hard here in a different way: a 6-hour-old value is off by {fm["gap_6h_lkv"]:.2f} ft because the tide has turned, and even a 15-minute-old one by {fm["mae_p15"]:.2f} ft.

## 8. A flood above the calibrated range (Hancock, leave-event-out)

{img(hk["image"])}

With the 29 July 2026 flood left out of calibration, the highest stage the model had seen was {hk["cal_max_ft"]:.2f} ft, and the river peaked at {hk["gauge_max_ft"]:.2f} ft. The rise happened overnight, when the camera posts no frames; by morning the model read roughly its calibrated ceiling all day. RMSE was {hk["rmse_ft"]:.2f} ft, while the Kalman σ stayed near {hk["median_kalman_sigma_ft"]:.2f} ft, so it was confidently wrong. Flood state was right on {100 * hk["flood_state_recall"]:.0f} % of frames. Lesson: readings near the top of the calibrated range must be reported as "at least this high", with a flag. Report §6.6.

## 9. Seasons drift

{img(sd["image"])}

Out-of-fold MAE of the frozen setting by month, from year-long forward-chaining CV (`seasonal_monthly_mae.csv`). A single camera's error can change several-fold from one month to the next (Bean Creek and Neversink both jump in March 2026, then recover). The fleet's monthly median moves between {sd["monthly_median_mae_min"]:.3f} and {sd["monthly_median_mae_max"]:.3f} ft without a clean seasonal curve, partly because the set of cameras with history grows through the year. The year-long median ({sd["year_cv_median_mae_ft"]} ft) is about twice the test-day median ({sd["test_median_mae_ft"]} ft). Two effects are confounded: the scene changing with the season, and early folds training on only a month or two of data. Periodic recalibration of the live models is the mitigation.
"""
    (OUT / "README.md").write_text(md, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cases = []
    summ = json.loads((RES / "kill_test_v2_summary.json").read_text(encoding="utf-8"))
    reg = pd.read_csv(RES / "kill_test" / "registration_summary.csv")

    # 1. night / IR
    cam = "NY_East_Branch_Delaware_River_at_Hancock_Staff"
    r = reg_table(cam)
    nights = r[r.night & (r.t >= TEST0) & (r.t < TEST1)]
    day = r[~r.night & r.ok & (r.t >= TEST0) & (r.t < TEST1)]
    n_img = nights.iloc[len(nights) // 2]
    d_img = day.iloc[len(day) // 2]
    img = pair(frame(cam, d_img.filename), f"day {d_img.t:%Y-%m-%d %H:%M}Z: scored",
               frame(cam, n_img.filename), f"night {n_img.t:%Y-%m-%d %H:%M}Z: not scored")
    cases.append({"id": "night_ir", "cam_id": cam, "image": save("night_ir_hancock.jpg", credit(img)),
                  "night_frames_30d": int(reg.night_sun.sum()), "frames_30d": int(reg.frames.sum()),
                  "night_share_30d": round(float(reg.night_sun.sum() / reg.frames.sum()), 3)})

    # 2. fog / wet lens: worst and best daylight frames by fog score in the 30-day cache
    cam = "NJ_Big_Brook_near_Marlboro"
    r = reg_table(cam)
    d = r[~r.night].copy()
    q = [image_quality(cv2.imread(str(RAW / cam / f))) for f in d.filename]
    d["fog"] = [x["fog_score"] for x in q]
    d["lap"] = [x["lap_var"] for x in q]
    bad, good = d.sort_values("fog").iloc[-1], d[d.ok].sort_values("fog").iloc[0]
    img = pair(frame(cam, good.filename), f"clear: fog {good.fog:.2f}, sharpness {good.lap:.0f}, registered",
               frame(cam, bad.filename), f"hazy, wet lens, high flow: fog {bad.fog:.2f}, sharpness {bad.lap:.0f}, "
                                         f"{'registered' if bad.ok else 'not registered'}")
    k = kt(cam)
    cases.append({"id": "fog_lens", "cam_id": cam, "image": save("fog_lens_bigbrook.jpg", credit(img)),
                  "fog_bad": round(float(bad.fog), 3), "lap_bad": round(float(bad.lap), 1), "bad_registered": bool(bad.ok),
                  "fog_good": round(float(good.fog), 3), "lap_good": round(float(good.lap), 1),
                  "test_reg_rate": float(k.reg_rate), "test_frames": int(k.n)})

    # 3. view change after a flood: White Rock reference vs a test-day frame that does not register
    cam = "TX_White_Rk_Ck_at_Greenville_Ave_Dallas"
    r = reg_table(cam)
    fail = r[~r.night & ~r.ok & (r.t >= TEST0) & (r.t < TEST1)]
    ref = r.ref.dropna().iloc[0]
    f = fail.iloc[len(fail) // 2]
    img = pair(frame(cam, Path(ref).name), "calibration reference",
               frame(cam, f.filename), f"test day {f.t:%Y-%m-%d %H:%M}Z: registration failed")
    k = kt(cam)
    cases.append({"id": "view_change_whiterock", "cam_id": cam, "image": save("view_change_whiterock.jpg", credit(img)),
                  "test_reg_rate": float(k.reg_rate), "mae_ft": float(k.mae), "p1": bool(k.p1), "p2": bool(k.p2),
                  "failed_daylight_test_frames": int(len(fail))})

    # 4. history view changes: Pecatonica reference vs an unlinked history segment's reference
    cam = "WI_East_Branch_Pecatonica_River_near_Blanchardville_Bullet"
    seg = pd.read_csv(DER / cam / "history" / "segments.csv")
    un = seg[~seg.linked.astype(bool)].sort_values("n_frames").iloc[-1]
    main_ref = reg_table(cam).ref.dropna().iloc[0]
    img = pair(frame(cam, Path(main_ref).name), "current reference",
               frame(cam, un.seg_ref), f"history {un.start}..{un.end}: different view, not linked")
    cases.append({"id": "view_change_pecatonica", "cam_id": cam, "image": save("view_change_pecatonica.jpg", credit(img)),
                  "unlinked_segments": summ["history_view_segments"]["per_site_unlinked"][cam],
                  "segment_frames": int(un.n_frames), "segment_start": un.start, "segment_end": un.end,
                  "sites_with_unlinked_segments": summ["history_view_segments"]["sites_with_unlinked_segments"]})

    # 5–7. time-series failures already plotted by the frozen scorer
    for cid, cam in (("diurnal_artifact_tenmile", "TX_Tenmile_Ck_at_Parkinson_Rd_nr_Ferris"),
                     ("far_bank_rootriver", "MN_Root_River_near_Pilot_Mound"),
                     ("tidal_firstmallard", "CA_First_Mallard_Branch_nr_Fairfield")):
        k = kt(cam)
        cases.append({"id": cid, "cam_id": cam, "image": f"results/kill_test_v2/{cam}_ts.png",
                      "floodheight": f"results/kill_test_v2/{cam}_floodheight.png",
                      "mae_ft": float(k.mae), "spearman": float(k.spearman), "sigma_ft": float(k.sigma),
                      "n_roi": int(k.n_roi), "mae_p15": float(k.mae_p15), "test_range_ft": float(k.test_range_ft),
                      "gap_6h_lkv": float(k.gap_6h_lkv), "p1": bool(k.p1)})

    # 8. flood above the calibrated range (Hancock, leave-event-out)
    cam = "NY_East_Branch_Delaware_River_at_Hancock_Staff"
    p = pd.read_csv(RES / "headtohead_hancock" / "pred_jul29.csv", parse_dates=["time"])
    m = pd.read_csv(RES / "headtohead_hancock" / "metrics.csv").set_index("event").loc["jul29"]
    s = pd.read_parquet(DER / cam / "history" / "stage.parquet")
    g = pd.Series(s["value"].to_numpy(float), index=pd.DatetimeIndex(s["time"]))
    t = pd.DatetimeIndex(p.time)
    # band = the event RMSE, so the plot does not echo the overconfident Kalman σ
    img = timeseries_png(g, t, p.camera_ft.to_numpy(), float(m.rmse), np.zeros(len(p), bool),
                         f"Hancock 29-30 Jul 2026, flood left out of calibration (cal max {m.cal_max_ft:.2f} ft); band = +/- event RMSE")
    cases.append({"id": "above_calibrated_range_hancock", "cam_id": cam, "image": save("above_range_hancock.png", img),
                  "rmse_ft": float(m.rmse), "cal_max_ft": float(m.cal_max_ft), "gauge_max_ft": float(m.gauge_max_ft),
                  "flood_state_recall": float(m.flood_state_recall), "median_kalman_sigma_ft": float(m.median_kalman_sigma_ft)})

    # 9. seasonal drift: out-of-fold MAE by month, frozen setting, year-long forward chaining
    key = "4|0.8|1.0|kalman"
    rows = []
    for f in sorted(DER.glob("*/tune_cv.npz")):
        z = np.load(f)
        P = z["P"][list(z["keys"]).index(key)]
        ok = np.isfinite(P)
        df = pd.DataFrame({"fold": z["fold"][ok], "err": np.abs(P[ok] - z["h"][ok])})
        for fold, gdf in df.groupby("fold"):
            rows.append({"cam_id": f.parent.name, "month": fold, "n": len(gdf), "mae_ft": round(float(gdf.err.mean()), 4)})
    sm = pd.DataFrame(rows)
    sm.to_csv(OUT / "seasonal_monthly_mae.csv", index=False)
    span = sm.groupby("cam_id").month.nunique().sort_values(ascending=False)
    pick = [c for c in span.index if c in ("WI_East_Branch_Pecatonica_River_near_Blanchardville_Bullet",
                                           "NY_Neversink_River_at_Godeffroy", "CO_Animas_River_at_Durango",
                                           "OH_Bean_Creek_at_Powers")] or list(span.index[:4])
    series = {c.split("_", 1)[1].replace("_", " "): sm[sm.cam_id == c].set_index("month").mae_ft for c in pick}
    img = line_chart(series, "Out-of-fold MAE by month (frozen setting, forward-chaining CV)", "MAE, ft")
    med = sm.groupby("month").mae_ft.median()
    cases.append({"id": "seasonal_drift", "cam_id": "fleet", "image": save("seasonal_drift.png", img),
                  "csv": "results/failures/seasonal_monthly_mae.csv", "sites": pick,
                  "year_cv_median_mae_ft": summ["year_cv"]["median_mae_ft"], "test_median_mae_ft": summ["median_mae_ft"],
                  "monthly_median_mae_min": round(float(med.min()), 3), "monthly_median_mae_max": round(float(med.max()), 3)})

    (OUT / "cases.json").write_text(json.dumps(cases, indent=1, default=str) + "\n", encoding="utf-8")
    write_readme({c["id"]: c for c in cases})
    for c in cases:
        print(c["id"], {k: v for k, v in c.items() if k not in ("id", "image")})


if __name__ == "__main__":
    main()
