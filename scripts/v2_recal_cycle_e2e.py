"""W4 (D-0014 W4-1): the recal wiring end to end through the REAL live step (needs the cycle.py recal patch).

1. live.cycle.replay drives run_site over cached Tenmile frames of Oct 10–12 into a local store
   (no agent); shadow_v2 computes F, P and the patch logs them with the matched gauge;
2. recal.load_logged reads them back; each logged F, P is compared with the training caches for the same frame
   (scene_kill30_test features, dino_live tokens), which proves the live features equal the training features;
3. the base cut at Oct 3 is put in the store and recal.refit_site refits from base + logged readings.

  python scripts/v2_recal_cycle_e2e.py --bundles <repo>/models/sites   → results/v2/recal_cycle_e2e.json
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
DATA = Path(os.environ.get("RIVERSIGHT_DATA", ROOT / "data"))
CAM = "TX_Tenmile_Ck_at_Parkinson_Rd_nr_Ferris"


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundles", type=Path, help="v1 bundles dir (models/sites is gitignored, so worker-q "
                                                   "snapshots need the absolute path of the live repo's copy)")
    a = ap.parse_args()
    if a.bundles:
        os.environ["RIVERSIGHT_BUNDLES"] = str(a.bundles)
    from riversight.calib import recal as R
    from riversight.live import cycle as C
    from riversight.live.store import LocalStore
    tmp = Path(tempfile.mkdtemp(prefix="recal_cycle_e2e_"))
    try:
        t0 = time.time()
        rows = C.replay(CAM, "2026-10-10", "2026-10-13", tmp, agent_fn=None, bundles=C.BUNDLES)
        replay_s = time.time() - t0
        store = LocalStore(tmp)
        got = R.load_logged(store, CAM)
        n_shadow = sum(1 for r in rows if r.get("shadow_stage_ft") is not None)
        z = np.load(DATA / "derived" / CAM / "scene_kill30_test.npz")
        zd = np.load(DATA / "derived" / CAM / "dino_live.npz")
        tf = pd.DatetimeIndex(pd.to_datetime(z["t"], utc=True))
        tdn = pd.DatetimeIndex(pd.to_datetime(zd["t"], utc=True))
        dF, dP, mF, mP, cF, cP, matched = [], [], [], [], [], [], 0
        for i, t in enumerate(got["t"]):
            j, k = tf.get_indexer([t])[0], tdn.get_indexer([t])[0]
            if j >= 0 and k >= 0:
                matched += 1
                a, b = got["F"][i].astype(np.float32), z["F"][j].astype(np.float32)
                c, d = got["P"][i].astype(np.float32), zd["P"][k].astype(np.float32)
                dF.append(float(np.abs(a - b).max()))
                dP.append(float(np.abs(c - d).max()))
                mF.append(float(np.median(np.abs(a - b))))
                mP.append(float(np.median(np.abs(c - d))))
                cF.append(float(np.corrcoef(a.ravel(), b.ravel())[0, 1]))
                cP.append(float(np.corrcoef(c.ravel(), d.ravel())[0, 1]))
        from v2_export_bundles import training_set
        t, h, F, P, _ = training_set(CAM, pd.Timestamp("2026-10-03", tz="UTC"))
        b = io.BytesIO()
        np.savez_compressed(b, t=pd.DatetimeIndex(t).as_unit("ns").asi8, h=h, F=F, P=P)
        store.put_bytes(R.BASE_KEY.format(cam=CAM), b.getvalue())
        res = R.refit_site(store, CAM, C.SHADOW_DIR, tmp / "sites_recal", min_new=5, now=got["t"][-1] if len(got["t"]) else None)
        out = {"cam_id": CAM, "replayed_readings": len(rows), "readings_with_v2_shadow": n_shadow,
               "logged_keys": got["n_keys"], "logged_usable": int(len(got["t"])), "replay_s": round(replay_s, 1),
               "matched_to_training_cache": matched,
               "max_abs_diff_F_vs_cache": max(dF) if dF else None, "max_abs_diff_P_vs_cache": max(dP) if dP else None,
               "median_abs_diff_F_vs_cache": float(np.median(mF)) if mF else None,
               "median_abs_diff_P_vs_cache": float(np.median(mP)) if mP else None,
               "min_corr_F_vs_cache": min(cF) if cF else None, "median_corr_F_vs_cache": float(np.median(cF)) if cF else None,
               "min_corr_P_vs_cache": min(cP) if cP else None, "median_corr_P_vs_cache": float(np.median(cP)) if cP else None,
               "note": "live replay re-registers each frame (live SiteRegistrar), so its H can differ from the cached "
                       "training H; differences reflect registration, not feature code (test_bundle: same H → same F)",
               "refit": res}
        print(json.dumps(out, indent=2, default=str))
        (ROOT / "results" / "v2" / "recal_cycle_e2e.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
