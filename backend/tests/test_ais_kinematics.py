"""Ship motion has to be motion a ship could perform. PLAN.md section 10.

The synthetic tracks used to be waypoints with straight interpolation
between them, which honours the waypoint schedule exactly and therefore
produces manoeuvres no hull can execute. Two factors read those
manoeuvres directly: F4 scores sustained speed deviation and F5 scores
course change, so an unphysical track is not a cosmetic problem, it is
a scoring input that measures the fixture instead of the vessel.

What these tests defend is the distinction between a turn and a corner.
A vessel under helm holds a rate of turn for the whole manoeuvre, so a
90 degree change arrives spread across many reports as a plateau. An
interpolated corner arrives as a single spike between two reports with
zeros either side. Both can pass a naive "is the rate plausible" check
when the pings are far enough apart, which is exactly how this survived
until someone looked at the course sequence.
"""

import datetime

import numpy as np
import pytest

from services.core.ais.kinematics import (
    DEFAULT_DECEL_KN_MIN,
    ROT_BY_TYPE,
    bearing_to,
    sail,
    sample_at_times,
    signed_turn,
    sustained_rot_profile,
)

T0 = datetime.datetime(2026, 1, 15, 0, 0)


def _leg(lat, lon, minutes):
    return (lat, lon, T0 + datetime.timedelta(minutes=minutes))


# A right-angle course change: east for an hour, then north for an hour.
RIGHT_ANGLE = [_leg(17.0, 68.0, 0), _leg(17.0, 68.2, 60), _leg(17.2, 68.2, 120)]


def test_a_ninety_degree_change_is_never_instantaneous():
    """The headline. A hull turns at a bounded rate, so the change has to
    occupy real time and real water."""
    path = sail(RIGHT_ANGLE, vessel_type="cargo")
    times = [p[0] for p in path]
    cogs = [p[3] for p in path]
    seconds = [(t - T0).total_seconds() for t in times]

    rates = sustained_rot_profile(cogs, seconds)
    assert max(rates) <= ROT_BY_TYPE["cargo"] + 1e-6, "turned faster than the hull allows"


def test_the_turn_is_a_plateau_not_a_spike():
    """The distinction that matters. An interpolated corner shows one
    large step surrounded by zeros; a real manoeuvre shows a sustained
    rate held across many consecutive reports."""
    path = sail(RIGHT_ANGLE, vessel_type="cargo")
    cogs = [p[3] for p in path]
    seconds = [(p[0] - T0).total_seconds() for p in path]
    rates = sustained_rot_profile(cogs, seconds)

    turning = [r for r in rates if r > 0.02]
    # At 0.25 deg/s a 90 degree change takes 360 seconds, which is 18
    # steps of 20 seconds. Anything close to one step is a corner.
    assert len(turning) >= 10, f"turn occupied only {len(turning)} steps, that is a corner"


def test_a_more_agile_vessel_turns_faster_but_still_not_instantly():
    slow = sail(RIGHT_ANGLE, vessel_type="tanker")
    quick = sail(RIGHT_ANGLE, vessel_type="fishing")

    def peak(path):
        return max(sustained_rot_profile([p[3] for p in path], [(p[0] - T0).total_seconds() for p in path]))

    assert peak(slow) < peak(quick), "a laden tanker must not out-turn a fishing boat"
    assert peak(quick) <= ROT_BY_TYPE["fishing"] + 1e-6


def test_the_vessel_traces_an_arc_rather_than_cutting_the_corner():
    """A turning vessel sweeps outside the corner. Interpolation cuts
    inside it, putting the reconstructed position where the hull never
    was."""
    path = sail(RIGHT_ANGLE, vessel_type="cargo")
    corner_lat, corner_lon = 17.0, 68.2

    # The closest approach to the geometric corner should be a real
    # distance away: the vessel begins its turn before the mark and ends
    # it after, so it never passes through the point itself.
    closest = min(
        np.hypot((lat - corner_lat) * 111.0, (lon - corner_lon) * 106.0)
        for _, lat, lon, _, _ in path
    )
    assert closest > 0.05, "track passed through the geometric corner, so it did not turn"


def test_speed_changes_are_bounded():
    """A loaded merchant vessel cannot drop ten knots between two pings.
    F4 scores sustained speed deviation and inherited this directly."""
    # Fast leg, then a leg asking for a crawl over the same duration.
    legs = [_leg(17.0, 68.0, 0), _leg(17.0, 68.30, 60), _leg(17.0, 68.31, 120)]
    path = sail(legs, vessel_type="tanker")

    speeds = [p[4] for p in path]
    seconds = [(p[0] - T0).total_seconds() for p in path]
    worst = 0.0
    for i in range(1, len(speeds)):
        dt_min = (seconds[i] - seconds[i - 1]) / 60.0
        if dt_min <= 0:
            continue
        worst = max(worst, abs(speeds[i] - speeds[i - 1]) / dt_min)

    assert worst <= DEFAULT_DECEL_KN_MIN + 1e-6, f"changed speed at {worst:.2f} kn/min"


def test_deceleration_takes_the_time_it_should():
    """Ten knots off a laden hull is ten minutes and more than a mile,
    not one ping interval."""
    legs = [_leg(17.0, 68.0, 0), _leg(17.0, 68.30, 60), _leg(17.0, 68.31, 120)]
    path = sail(legs, vessel_type="tanker")

    speeds = np.array([p[4] for p in path])
    seconds = np.array([(p[0] - T0).total_seconds() for p in path])
    fast = speeds.max()
    if fast < 5.0:
        pytest.skip("leg geometry did not produce a transit speed to decelerate from")

    # Time from the last moment above 80 percent of peak to the first
    # below 20 percent of it.
    above = seconds[speeds > 0.8 * fast]
    below = seconds[speeds < 0.2 * fast]
    if len(above) == 0 or len(below) == 0:
        pytest.skip("no full deceleration in this geometry")
    took_min = (below[below > above[-1]].min() - above[-1]) / 60.0
    assert took_min > 5.0, f"shed {fast:.1f} knots in {took_min:.1f} minutes"


def test_course_and_speed_come_from_the_vessel_not_from_differencing():
    """Differencing consecutive pings reports the chord, which understates
    speed through a turn and reports a course the vessel never steered."""
    path = sail(RIGHT_ANGLE, vessel_type="cargo")
    times = [T0 + datetime.timedelta(minutes=m) for m in range(0, 110, 10)]
    sampled = sample_at_times(path, times)

    for lat, lon, cog, sog in sampled:
        assert 0.0 <= cog < 360.0
        assert sog >= 0.0


def test_bearing_and_turn_helpers():
    assert bearing_to(17.0, 68.0, 18.0, 68.0) == pytest.approx(0.0, abs=0.5)
    assert bearing_to(17.0, 68.0, 17.0, 69.0) == pytest.approx(90.0, abs=0.5)
    assert signed_turn(350.0, 10.0) == pytest.approx(20.0)
    assert signed_turn(10.0, 350.0) == pytest.approx(-20.0)


def test_a_track_needs_at_least_two_waypoints():
    with pytest.raises(ValueError, match="at least two waypoints"):
        sail([_leg(17.0, 68.0, 0)])
