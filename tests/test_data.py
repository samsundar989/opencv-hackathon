from datetime import datetime, timezone

import pandas as pd

from riversight.data.join import frames_table, join_frames_to_stage, stage_variability
from riversight.data.nims import camera_from_record, image_url, parse_filename, select_cameras
from riversight.data.nwis import features_to_frame


def test_parse_filename():
    cam, dt = parse_filename("TX_Guadalupe_Rv_at_Comfort___2026-10-10T11-41-21Z.jpg")
    assert cam == "TX_Guadalupe_Rv_at_Comfort"
    assert dt == datetime(2026, 10, 10, 11, 41, 21, tzinfo=timezone.utc)


def test_image_url():
    assert image_url("A_B", "A_B___2026-01-01T00-00-00Z.jpg") == \
        "https://usgs-nims-images.s3.amazonaws.com/overlay/A_B/A_B___2026-01-01T00-00-00Z.jpg"
    assert image_url("A_B", "f.jpg", "720").startswith("https://usgs-nims-images.s3.amazonaws.com/720/A_B/")


def test_camera_record_and_selection():
    now = datetime(2026, 10, 13, 23, 0, tzinfo=timezone.utc)
    rec = {"camId": "IL_Lick_Creek_near_Woodside", "nwisId": "05576100", "camName": "Lick Creek near Woodside",
           "lat": "39.71553889", "lng": "-89.7024444", "stateAbrv": "IL", "tz": "US/Central",
           "createdDate": "2023-04-24T00:46:41.885Z", "newestImageDT": "2026-10-13T11:45:02.000Z", "hideCam": False}
    c = camera_from_record(rec)
    assert c.gauged and c.active(48, now) and c.age_days(now) > 1000
    new = camera_from_record({**rec, "camId": "X", "createdDate": "2026-09-29T19:55:14.255Z"})
    hidden = camera_from_record({**rec, "camId": "Y", "hideCam": True})
    ungauged = camera_from_record({**rec, "camId": "Z", "nwisId": ""})
    sel = select_cameras([c, new, hidden, ungauged], min_age_days=90, now=now)
    assert [x.cam_id for x in sel] == ["IL_Lick_Creek_near_Woodside"]
    assert select_cameras([c], states={"TX"}, now=now) == []


def test_features_to_frame():
    feats = [{"properties": {"time": "2026-10-10T00:00:00+00:00", "value": "3.35", "unit_of_measure": "ft",
                             "approval_status": "Provisional", "qualifier": None, "time_series_id": "t1",
                             "monitoring_location_id": "USGS-08167000"}},
             {"properties": {"time": "2026-10-10T00:15:00+00:00", "value": "bad"}}]
    df = features_to_frame(feats)
    assert len(df) == 1 and df.loc[0, "value"] == 3.35 and str(df.loc[0, "time"].tz) == "UTC"


def test_join_interpolates_within_tolerance():
    files = ["C___2026-10-10T00-07-30Z.jpg", "C___2026-10-10T03-00-00Z.jpg"]
    frames = frames_table(files)
    stage = pd.DataFrame({"time": pd.to_datetime(["2026-10-10T00:00:00Z", "2026-10-10T00:15:00Z"]),
                          "value": [3.0, 4.0]})
    j = join_frames_to_stage(frames, stage, tolerance_min=10)
    assert abs(j.loc[0, "stage_ft"] - 3.5) < 1e-9       # halfway between the two readings
    assert pd.isna(j.loc[1, "stage_ft"])                 # 3 hours away → no label
    v = stage_variability(stage)
    assert v["n"] == 2 and abs(v["range_ft"] - 1.0) < 1e-9


def test_long_retry_after_raises_instead_of_retrying():
    """Bug (Oct 14): 429s were retried with backoff, and each retry burned hourly quota."""
    import httpx
    import pytest
    from riversight.data.nwis import NwisClient, RateLimited

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"retry-after": "1033"})

    c = NwisClient(api_key="x")
    c._http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RateLimited):
        c._get("https://example.invalid/items")
    assert len(calls) == 1


def test_parse_waterml_json():
    from riversight.data.nwis import parse_waterml_json
    data = {"value": {"timeSeries": [{"sourceInfo": {"siteCode": [{"value": "05576100"}]},
                                      "variable": {"noDataValue": -999999.0},
                                      "values": [{"value": [{"dateTime": "2026-10-10T00:00:00.000-05:00", "value": "3.5"},
                                                            {"dateTime": "2026-10-10T00:15:00.000-05:00", "value": "-999999"}]}]}]}}
    out = parse_waterml_json(data)
    assert list(out) == ["05576100"] and len(out["05576100"]) == 1
    assert out["05576100"]["time"].iloc[0] == __import__("pandas").Timestamp("2026-10-10T05:00:00Z")


def test_legacy_iv_follows_redirect(monkeypatch):
    # waterservices.usgs.gov answers 301 → nwis.waterservices.usgs.gov (Oct 2026); the client must follow it
    import httpx
    from riversight.data import nwis
    seen = {}

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"value": {"timeSeries": []}}

    def fake_get(url, **kw):
        seen.update(kw, url=url)
        return R()
    monkeypatch.setattr(httpx, "get", fake_get)
    from datetime import datetime, timezone
    nwis.legacy_iv_multi(["01481500"], datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert seen["follow_redirects"] is True and seen["url"].startswith("https://nwis.waterservices.usgs.gov/")
