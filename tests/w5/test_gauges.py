import numpy as np
import pandas as pd

from riversight.onboard.gauges import parse_waterml_qualified, scan_outages


def _series(times, values, quals):
    return pd.DataFrame({"time": pd.to_datetime(times, utc=True), "value": values, "quals": quals})


def test_gap_detected_with_bracketing_values():
    t = list(pd.date_range("2026-01-01", periods=8, freq="15min", tz="UTC")) + \
        list(pd.date_range("2026-01-01 10:00", periods=4, freq="15min", tz="UTC"))
    v = [1.0] * 8 + [2.0] * 4
    ev = scan_outages(_series(t, v, ["P"] * 12), min_gap_h=6)
    assert len(ev) == 1 and ev[0]["kind"] == "gap"
    assert ev[0]["v_before"] == 1.0 and ev[0]["v_after"] == 2.0
    assert abs(ev[0]["hours"] - 8.25) < 1e-6


def test_short_gap_ignored_and_edges_not_outages():
    t = list(pd.date_range("2026-01-01", periods=8, freq="15min", tz="UTC")) + \
        list(pd.date_range("2026-01-01 05:00", periods=4, freq="15min", tz="UTC"))
    assert scan_outages(_series(t, [1.0] * 12, ["A"] * 12), min_gap_h=6) == []


def test_estimated_and_ice_runs():
    t = pd.date_range("2026-01-01", periods=60, freq="15min", tz="UTC")     # 14.75 h
    q = ["A"] * 5 + ["A,e"] * 30 + ["A"] * 25
    ev = scan_outages(_series(t, np.ones(60), q), min_gap_h=6)
    assert [e["kind"] for e in ev] == ["estimated"]
    q2 = ["P"] * 5 + ["P,Ice"] * 40 + ["P"] * 15
    v2 = np.r_[np.ones(5), np.full(40, np.nan), np.ones(15)]
    ev2 = scan_outages(_series(t, v2, q2), min_gap_h=6)
    kinds = sorted(e["kind"] for e in ev2)
    assert kinds == ["gap", "qualified"]
    assert next(e for e in ev2 if e["kind"] == "qualified")["codes"] == "Ice"


def test_parse_keeps_nodata_qualifiers():
    data = {"value": {"timeSeries": [{
        "sourceInfo": {"siteCode": [{"value": "01234567"}]},
        "variable": {"noDataValue": -999999.0},
        "values": [{"value": [
            {"value": "3.2", "qualifiers": ["P"], "dateTime": "2026-01-01T00:00:00.000-06:00"},
            {"value": "-999999", "qualifiers": ["P", "Eqp"], "dateTime": "2026-01-01T00:15:00.000-06:00"}]}]}]}}
    df = parse_waterml_qualified(data)["01234567"]
    assert len(df) == 2 and np.isnan(df["value"].iloc[1]) and df["quals"].iloc[1] == "P,Eqp"
    assert str(df["time"].iloc[0]) == "2026-01-01 06:00:00+00:00"
