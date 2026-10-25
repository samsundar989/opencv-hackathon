"""W4 recal wiring in the live cycle (D-0014): job launcher schedule, recal shadow, kill switch."""
import json

import numpy as np
import pandas as pd

import riversight.live.cycle as C
from riversight.calib.scene_v2 import fit_bundle, parse_config
from riversight.live.store import LocalStore, S3Store


class FakeS3(S3Store):
    """S3Store interface over a local directory (no boto3)."""
    def __init__(self, root):
        self._l = LocalStore(root)
        self.bucket = "test-bucket"

    def get_json(self, key):
        return self._l.get_json(key)

    def put_json(self, key, obj, cache=None):
        self._l.put_json(key, obj)


def _launches(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(C.subprocess, "Popen", lambda *a, **k: calls.append(a[0]))
    monkeypatch.setattr(C, "RECAL_LOCK", tmp_path / "recal.lock")
    return calls


def test_jobs_schedule_refit_monday_6utc_then_hourly_drift(monkeypatch, tmp_path):
    calls = _launches(monkeypatch, tmp_path)
    store = FakeS3(tmp_path / "s3")
    assert C.maybe_recal_jobs(store, pd.Timestamp("2026-10-26 06:10", tz="UTC")) == "refit"     # Monday 06 UTC
    assert C.maybe_recal_jobs(store, pd.Timestamp("2026-10-26 06:25", tz="UTC")) is None        # lock held
    (tmp_path / "recal.lock").unlink()
    store.put_json("live/recal/models/_last_run.json", {"finished": "2026-10-26T06:20:00+00:00"})
    assert C.maybe_recal_jobs(store, pd.Timestamp("2026-10-26 06:40", tz="UTC")) == "drift"     # refit done → drift
    (tmp_path / "recal.lock").unlink()
    assert C.maybe_recal_jobs(store, pd.Timestamp("2026-10-26 07:00", tz="UTC")) is None        # drift < 55 min ago
    assert len(calls) == 2 and any("refit" in " ".join(map(str, c)) for c in calls)


def test_jobs_disabled_by_env_and_on_local_store(monkeypatch, tmp_path):
    calls = _launches(monkeypatch, tmp_path)
    monkeypatch.setenv("RIVERSIGHT_RECAL", "0")
    assert C.maybe_recal_jobs(FakeS3(tmp_path / "s3"), pd.Timestamp("2026-10-26 06:10", tz="UTC")) is None
    monkeypatch.delenv("RIVERSIGHT_RECAL")
    assert C.maybe_recal_jobs(LocalStore(tmp_path / "l"), pd.Timestamp("2026-10-26 06:10", tz="UTC")) is None
    assert calls == []


def test_recal_shadow_scores_and_keeps_its_own_kalman(monkeypatch, tmp_path):
    rng = np.random.default_rng(0)
    n = 60
    t = pd.date_range("2026-06-01 14:00", periods=n, freq="5h", tz="UTC")
    h = np.linspace(2, 3, n)
    F = rng.normal(size=(n, 3600, 5)).astype(np.float16)
    F[:, :300, 0] += h[:, None].astype(np.float16)
    P = rng.normal(size=(n, 448, 6)).astype(np.float16)
    d = tmp_path / "sites_recal" / "cam"
    d.mkdir(parents=True)
    np.savez(d / "scene_model_v2.npz", **fit_bundle(F, P, t, h, parse_config("v1+dino_roi@0.5+sun"), 32.8, -96.8, q=0.01))
    (d / "meta_v2.json").write_text(json.dumps({"lat": 32.8, "lon": -96.8, "model_sha": "abc123def456789"}))
    monkeypatch.setattr(C, "RECAL_DIR", tmp_path / "sites_recal")
    state = {}
    frame = C.Frame("x.jpg", t[-1].to_pydatetime(), None)
    out = C.recal_shadow("cam", F[-1].astype(np.float32), P[-1], frame, state)
    assert np.isfinite(out["recal_shadow_ft"]) and out["recal_model_sha"] == "abc123def456"
    assert "kalman_recal" in state and "kalman_v2" not in state
    assert C.recal_shadow("absent", F[-1], P[-1], frame, state) is None
