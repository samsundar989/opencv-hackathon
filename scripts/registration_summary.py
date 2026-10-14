"""SLICE_01: QA'd registration summary over all kill-test sites (from cached homographies; no images).
Writes results/kill_test/registration_summary.csv.

  python scripts/registration_summary.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from riversight.killtest import Cfg, qa_registration, site_latlng, thin_frames  # noqa: E402


def main():
    doc = yaml.safe_load((ROOT / "data/sites/kill_test.yaml").read_text(encoding="utf-8"))
    t1 = pd.Timestamp(doc["window"]["end"]); t0 = t1 - pd.Timedelta(days=doc["window"]["days"])
    rows = []
    for s in doc["sites"]:
        cam = s["cam_id"]; d = ROOT / "data/derived" / cam
        c = pd.read_parquet(d / "registration_cascade.parquet")
        fr = pd.read_parquet(d / "frames.parquet")
        fr = fr[(fr["time"] >= t0) & (fr["time"] < t1)].sort_values("time").reset_index(drop=True)
        fr = thin_frames(fr, Cfg().min_gap_min).reset_index(drop=True)
        reg = (fr[["filename"]].reset_index().merge(c.drop(columns="ref"), on="filename")
               .set_index("index").drop(columns="filename"))
        import cv2
        shape = cv2.imread(str(ROOT / "data/raw/720" / cam / c["ref"].iloc[0])).shape[:2]
        q = qa_registration(reg, fr, shape, site_latlng(ROOT / "data", cam), Cfg())
        day = q[~q["night"].astype(bool)]
        ok = day[day["ok"]]
        rows.append({"site": cam, "frames": len(q), "night_sun": int(q["night"].sum()),
                     "floodlit_night_caught": int((q["night"].astype(bool) & ~q["night_img"].fillna(False).astype(bool)).sum()),
                     "day": len(day), "registered": len(ok), "reg_rate": round(len(ok) / max(len(day), 1), 4),
                     "orb": int((ok["method"] == "orb").sum()), "aliked_lightglue": int((ok["method"] == "aliked+lightglue").sum()),
                     "chain": int(ok["method"].str.endswith("-chain").sum()),
                     "geo_rejected": int((day["ok_raw"].astype(bool) & ~day["ok"]).sum())})
    S = pd.DataFrame(rows)
    out = ROOT / "results/kill_test"; out.mkdir(parents=True, exist_ok=True)
    S.to_csv(out / "registration_summary.csv", index=False)
    tot = S[["day", "registered", "orb", "aliked_lightglue", "chain", "geo_rejected", "floodlit_night_caught"]].sum()
    print(S.to_string(index=False)); print("TOTAL", tot.to_dict(), "rate", round(tot["registered"] / tot["day"], 4))


if __name__ == "__main__":
    main()
