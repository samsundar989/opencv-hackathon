import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from onboard_outages import merge_events  # noqa: E402


def test_overlapping_kinds_merge_into_one_outage():
    T = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731
    cat = pd.DataFrame([
        {"cam_id": "c", "nwis_id": "1", "state": "TX", "kind": "gap", "start": T("2026-01-01 00:00"), "end": T("2026-01-02 00:00"),
         "hours": 24, "v_before": 1.0, "v_after": 2.0, "codes": ""},
        {"cam_id": "c", "nwis_id": "1", "state": "TX", "kind": "qualified", "start": T("2026-01-01 00:15"), "end": T("2026-01-01 23:45"),
         "hours": 23.5, "v_before": 1.0, "v_after": 2.0, "codes": "Ice"},
        {"cam_id": "c", "nwis_id": "1", "state": "TX", "kind": "estimated", "start": T("2026-02-01"), "end": T("2026-02-02"),
         "hours": 24, "v_before": 3.0, "v_after": 3.5, "codes": "e"},
    ])
    m = merge_events(cat)
    assert len(m) == 2
    first = m.iloc[0]
    assert first["kinds"] == "gap|qualified" and first["codes"] == "Ice" and first["truth"] == "after_return_only"
    assert first["v_before"] == 1.0 and first["v_after"] == 2.0 and np.isclose(first["hours"], 24)
    assert m.iloc[1]["truth"] == "usgs_estimated_backfill"
