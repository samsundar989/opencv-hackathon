"""D-0014 v2 serving (W5 as D-0015 deploy owner): the frozen-v1 prospective record keeps scoring v1's own number."""
import json

import pandas as pd

from riversight.live import cycle, prospective


class Store:
    def __init__(self, rows):
        self.b = "\n".join(json.dumps(r) for r in rows).encode()

    def get_bytes(self, key):
        return self.b if key.endswith("2026-10-25.jsonl") else None


def test_frozen_v1_scored_on_v1_number_after_v2_serves():
    base = {"cam_id": "C", "t_cycle": "2026-10-25T15:00:00Z", "daylight": True, "registration": {"ok": True},
            "model_sha": "v1sha", "flags": [], "mode": "live"}
    rows = [dict(base, t_frame="2026-10-25T14:00:00Z", camera_stage_ft=5.0, served_model="v1"),
            dict(base, t_frame="2026-10-25T15:00:00Z", camera_stage_ft=5.4, shadow_stage_ft=5.4, v1_stage_ft=5.1,
                 served_model="v2")]
    df = prospective.load_readings(Store(rows), ["C"], pd.Timestamp("2026-10-25", tz="UTC"), pd.Timestamp("2026-10-25 23:00", tz="UTC"))
    assert list(df["camera_ft"]) == [5.0, 5.1]                 # v1's own value, not the served v2 value
    assert list(df["served_model"]) == ["v1", "v2"] and list(df["shadow_ft"].fillna(-1)) == [-1, 5.4]


def test_serve_v2_switch(monkeypatch):
    monkeypatch.delenv("RIVERSIGHT_SERVE_V2", raising=False)
    assert not cycle.serve_v2()
    monkeypatch.setenv("RIVERSIGHT_SERVE_V2", "1")
    assert cycle.serve_v2()
