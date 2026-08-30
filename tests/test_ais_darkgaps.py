import datetime

import pytest
from shapely.geometry import Point, shape

from services.core.ais.darkgaps import dead_reckoned_envelope, find_dark_gaps
from services.core.schemas import AISPoint

T0 = datetime.datetime(2026, 1, 15, 0, 0)


def test_find_dark_gaps_ignores_short_intervals():
    points = [
        AISPoint(ts=T0, lat=10.0, lon=70.0, sog=10.0, cog=90.0),
        AISPoint(ts=T0 + datetime.timedelta(minutes=10), lat=10.0, lon=70.1, sog=10.0, cog=90.0),
    ]
    gaps = find_dark_gaps(points, min_gap_minutes=20, max_speed_kn=25)
    assert gaps == []


def test_find_dark_gaps_flags_long_intervals():
    points = [
        AISPoint(ts=T0, lat=10.0, lon=70.0, sog=10.0, cog=90.0),
        AISPoint(ts=T0 + datetime.timedelta(minutes=45), lat=10.0, lon=70.5, sog=10.0, cog=90.0),
    ]
    gaps = find_dark_gaps(points, min_gap_minutes=20, max_speed_kn=25)
    assert len(gaps) == 1
    assert gaps[0].duration_min == pytest.approx(45.0)
    assert gaps[0].entry_point == (70.0, 10.0)
    assert gaps[0].exit_point == (70.5, 10.0)


def test_find_dark_gaps_envelope_contains_both_endpoints():
    entry = AISPoint(ts=T0, lat=10.0, lon=70.0, sog=10.0, cog=90.0)
    exit_ = AISPoint(ts=T0 + datetime.timedelta(minutes=45), lat=10.0, lon=70.3, sog=10.0, cog=90.0)
    gaps = find_dark_gaps([entry, exit_], min_gap_minutes=20, max_speed_kn=25)
    envelope = shape(gaps[0].envelope)
    assert envelope.contains(Point(70.0, 10.0)) or envelope.touches(Point(70.0, 10.0)) or envelope.distance(Point(70.0, 10.0)) < 1e-6
    assert envelope.distance(Point(70.3, 10.0)) < 1e-6


def test_dead_reckoned_envelope_is_larger_for_longer_gaps():
    entry = AISPoint(ts=T0, lat=10.0, lon=70.0, sog=10.0, cog=90.0)
    short_exit = AISPoint(ts=T0 + datetime.timedelta(minutes=25), lat=10.0, lon=70.1, sog=10.0, cog=90.0)
    long_exit = AISPoint(ts=T0 + datetime.timedelta(hours=4), lat=10.0, lon=70.5, sog=10.0, cog=90.0)

    short_envelope = shape(dead_reckoned_envelope(entry, short_exit, max_speed_kn=25))
    long_envelope = shape(dead_reckoned_envelope(entry, long_exit, max_speed_kn=25))

    assert long_envelope.area > short_envelope.area


def test_find_dark_gaps_empty_for_no_gaps():
    points = [
        AISPoint(ts=T0, lat=10.0, lon=70.0, sog=10.0, cog=90.0),
        AISPoint(ts=T0 + datetime.timedelta(minutes=5), lat=10.0, lon=70.05, sog=10.0, cog=90.0),
        AISPoint(ts=T0 + datetime.timedelta(minutes=10), lat=10.0, lon=70.1, sog=10.0, cog=90.0),
    ]
    assert find_dark_gaps(points, min_gap_minutes=20, max_speed_kn=25) == []
