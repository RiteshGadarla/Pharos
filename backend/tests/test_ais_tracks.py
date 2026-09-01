import datetime

import pytest

from services.core.ais.tracks import (
    bearing_deg,
    course_and_speed_at,
    great_circle_interpolate,
    haversine_km,
    median_speed_kn,
    position_at,
)
from services.core.schemas import AISPoint, AISTrack, DarkGap

T0 = datetime.datetime(2026, 1, 15, 0, 0)
T1 = datetime.datetime(2026, 1, 15, 1, 0)
T2 = datetime.datetime(2026, 1, 15, 2, 0)


def _track():
    return AISTrack(
        mmsi="1",
        vessel_type="tanker",
        points=[
            AISPoint(ts=T0, lat=10.0, lon=70.0, sog=10.0, cog=90.0),
            AISPoint(ts=T1, lat=10.0, lon=71.0, sog=8.0, cog=100.0),
            AISPoint(ts=T2, lat=10.0, lon=72.0, sog=6.0, cog=110.0),
        ],
        dark_gaps=[],
    )


def test_great_circle_interpolate_at_endpoints_returns_endpoints():
    lat, lon = great_circle_interpolate(10.0, 70.0, 20.0, 80.0, 0.0)
    assert lat == pytest.approx(10.0)
    assert lon == pytest.approx(70.0)
    lat, lon = great_circle_interpolate(10.0, 70.0, 20.0, 80.0, 1.0)
    assert lat == pytest.approx(20.0)
    assert lon == pytest.approx(80.0)


def test_bearing_deg_due_east_is_90():
    assert bearing_deg(10.0, 70.0, 10.0, 71.0) == pytest.approx(90.0, abs=1.0)


def test_haversine_km_matches_known_distance():
    # 1 degree of longitude at the equator is about 111.2 km
    d = haversine_km(0.0, 0.0, 0.0, 1.0)
    assert d == pytest.approx(111.2, rel=0.01)


def test_position_at_interpolates_between_pings():
    track = _track()
    lat, lon = position_at(track, T0 + datetime.timedelta(minutes=30))
    assert lat == pytest.approx(10.0, abs=0.01)
    assert 70.0 < lon < 71.0


def test_position_at_returns_none_outside_track_range():
    track = _track()
    assert position_at(track, T0 - datetime.timedelta(minutes=10)) is None
    assert position_at(track, T2 + datetime.timedelta(minutes=10)) is None


def test_position_at_returns_none_inside_a_dark_gap():
    track = _track()
    track.dark_gaps.append(
        DarkGap(
            start=T0 + datetime.timedelta(minutes=10),
            end=T0 + datetime.timedelta(minutes=50),
            duration_min=40.0,
            entry_point=(70.1, 10.0),
            exit_point=(70.9, 10.0),
            envelope={"type": "Polygon", "coordinates": [[[70, 9.9], [70, 10.1], [71, 10.1], [71, 9.9], [70, 9.9]]]},
        )
    )
    assert position_at(track, T0 + datetime.timedelta(minutes=30)) is None
    # outside the gap, still works
    assert position_at(track, T0 + datetime.timedelta(minutes=55)) is not None


def test_course_and_speed_at_interpolates():
    track = _track()
    cog, sog = course_and_speed_at(track, T0 + datetime.timedelta(minutes=30))
    assert 90.0 < cog < 100.0
    assert 8.0 < sog < 10.0


def test_median_speed_kn():
    track = _track()
    assert median_speed_kn(track) == pytest.approx(8.0)
