"""W4 (D-0014 W4-1): weekly self-recalibration: log → refit → shadow bundle, with the local store."""
import io
import json

import numpy as np
import pandas as pd

from riversight.calib import recal as R
from riversight.calib.scene_v2 import ShadowV2, fit_bundle, parse_config
from riversight.live.store import LocalStore

CFG = "v1+dino_roi@0.5+sun"


def _data(n, t0, seed, hi=3.0):
    rng = np.random.default_rng(seed)
    t = pd.date_range(t0, periods=n, freq="5h", tz="UTC")
    h = np.linspace(2.0, hi, n) + rng.normal(scale=0.05, size=n)
    F = rng.normal(size=(n, 3600, 5)).astype(np.float16)
    F[:, :300, 0] += h[:, None].astype(np.float16)
    P = rng.normal(size=(n, 448, 6)).astype(np.float16)
    P[:, :40, 1] += (2 * h[:, None]).astype(np.float16)
    return t, h, F, P


def _setup(tmp_path):
    store = LocalStore(tmp_path / "s3")
    t, h, F, P = _data(90, "2026-06-01 14:00", 1)
    b = io.BytesIO()
    np.savez_compressed(b, t=t.asi8, h=h, F=F, P=P)
    store.put_bytes(R.BASE_KEY.format(cam="cam"), b.getvalue())
    bundles = tmp_path / "sites_v2"
    (bundles / "cam").mkdir(parents=True)
    arr = fit_bundle(F, P, t, h, parse_config(CFG), 32.8, -96.8, q=0.01)
    np.savez(bundles / "cam" / "scene_model_v2.npz", **arr)
    (bundles / "cam" / "meta_v2.json").write_text(json.dumps({"cam_id": "cam", "lat": 32.8, "lon": -96.8, "config": CFG,
                                                              "sigma_ft": 0.2, "model_sha": "parent"}))
    return store, bundles, (t, h, F, P)


def test_log_and_load_filters_unusable_readings(tmp_path):
    store = LocalStore(tmp_path)
    t, h, F, P = _data(4, "2026-10-20 15:00", 2)
    R.log_features(store, "cam", t[0], F[0], P[0], h[0], t[0] + pd.Timedelta("10min"), [], raw_ft=h[0] + 0.1)
    R.log_features(store, "cam", t[1], F[1], P[1], h[1], t[1] + pd.Timedelta("50min"), [])        # gauge too far
    R.log_features(store, "cam", t[2], F[2], P[2], h[2], t[2], ["VIEW_CHANGE"])                    # excluded flag
    R.log_features(store, "cam", t[3], F[3], P[3], None, None, [])                                 # no gauge
    got = R.load_logged(store, "cam")
    assert got["n_keys"] == 4 and len(got["t"]) == 1 and got["t"][0] == t[0]
    assert np.allclose(got["F"][0], F[0]) and np.isclose(got["raw"][0], h[0] + 0.1)


def test_refit_extends_stage_max_and_matches_direct_fit(tmp_path):
    store, bundles, (t, h, F, P) = _setup(tmp_path)
    tn, hn, Fn, Pn = _data(30, "2026-07-20 14:00", 3, hi=4.5)                   # a "flood" above the base range
    for i in range(30):
        R.log_features(store, "cam", tn[i], Fn[i], Pn[i], hn[i], tn[i], [], raw_ft=hn[i])
    res = R.refit_site(store, "cam", bundles, tmp_path / "sites_recal", min_new=20, now=tn[-1])
    assert res["status"] == "refit" and res["n_new"] == 30
    assert res["stage_max_after_ft"] > res["stage_max_before_ft"]
    sh = ShadowV2(tmp_path / "sites_recal" / "cam")
    assert sh.meta["n_new_frames"] == 30 and sh.meta["parent_model_sha"] == "parent"
    direct = fit_bundle(np.concatenate([F, Fn]), np.concatenate([P, Pn]), t.append(tn), np.concatenate([h, hn]),
                        parse_config(CFG), 32.8, -96.8, q=0.01)
    assert np.allclose(np.load(tmp_path / "sites_recal" / "cam" / "scene_model_v2.npz")["w"], direct["w"])
    assert store.get_json(f"{R.MODEL_PREFIX}/cam/meta_v2.json")["model_sha"] == sh.meta["model_sha"]
    assert np.isfinite(sh.predict_raw(Fn[-1].astype(np.float32), Pn[-1], tn[-1]))


def test_refit_skips_with_too_few_new_readings(tmp_path):
    store, bundles, _ = _setup(tmp_path)
    tn, hn, Fn, Pn = _data(5, "2026-07-20 14:00", 4)
    for i in range(5):
        R.log_features(store, "cam", tn[i], Fn[i], Pn[i], hn[i], tn[i], [])
    res = R.refit_site(store, "cam", bundles, tmp_path / "out", min_new=20)
    assert res["status"].startswith("skipped") and not (tmp_path / "out" / "cam").exists()


def test_drift_signal():
    now = pd.Timestamp("2026-10-25 12:00", tz="UTC")
    t = pd.date_range(now - pd.Timedelta("5D"), periods=30, freq="4h")
    h = np.full(30, 3.0)
    new = {"t": t, "h": h, "raw": h + 0.5}
    assert R.drift_report(new, sigma_ft=0.2, now=now)["drifting"]
    new["raw"] = h + 0.05
    assert not R.drift_report(new, sigma_ft=0.2, now=now)["drifting"]


def test_cli_one_site_never_blocks_others(tmp_path):
    store, bundles, _ = _setup(tmp_path)
    (bundles / "broken").mkdir()
    (bundles / "broken" / "meta_v2.json").write_text("{not json")
    rc = R.main(["refit", "--local", str(tmp_path / "s3"), "--bundles", str(bundles), "--out", str(tmp_path / "o")])
    last = store.get_json(f"{R.MODEL_PREFIX}/_last_run.json")
    assert rc == 1 and {r["cam_id"] for r in last["results"]} == {"cam", "broken"}
