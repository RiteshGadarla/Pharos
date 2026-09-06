"""The slick's age band constrains WHEN the discharge happened.

See PLAN.md sections 8 and 12. The backward field cannot distinguish a
48 hour old origin from a 1 hour old one: the drift physics has no
opinion about when the oil entered the water. The slick's own contrast
and complexity do, weakly, and this is the only place that evidence
reaches the ranking.

What is being defended here is mostly what the band is NOT allowed to
do. It must not become an age in hours, it must not cut off, and it must
not eliminate a vessel on its own.
"""

import datetime

import pytest

from services.core.scoring.age_window import (
    DEFAULT_FLOOR_WEIGHT,
    describe_window,
    field_time_weights,
    weight_at_lag,
    weighted_span_hours,
    window_for_band,
)

ACQUIRED_AT = datetime.datetime(2026, 1, 15, 2, 30)

CONFIG = {
    "bands": {"fresh": [0, 12], "intermediate": [6, 30], "weathered": [24, 48]},
    "taper_hours": 6.0,
    "floor_weight": 0.15,
}


def test_a_fresher_slick_implies_a_more_recent_origin():
    fresh = window_for_band("fresh", CONFIG)
    intermediate = window_for_band("intermediate", CONFIG)
    weathered = window_for_band("weathered", CONFIG)

    # The ordering is the whole physical claim: oil spreads and its
    # contrast falls with time on the surface.
    assert fresh[1] <= intermediate[1] <= weathered[1]
    assert fresh[0] <= intermediate[0] <= weathered[0]


def test_the_bands_overlap():
    """They must. A hard partition would assert that a slick one dB
    either side of the fresh threshold originated in two disjoint time
    windows, which the radiometry cannot support."""
    fresh = window_for_band("fresh", CONFIG)
    intermediate = window_for_band("intermediate", CONFIG)
    assert intermediate[0] < fresh[1], "fresh and intermediate must overlap"


def test_full_weight_inside_the_window():
    window = window_for_band("fresh", CONFIG)
    assert weight_at_lag(0.0, window, CONFIG) == pytest.approx(1.0)
    assert weight_at_lag(6.0, window, CONFIG) == pytest.approx(1.0)
    assert weight_at_lag(12.0, window, CONFIG) == pytest.approx(1.0)


def test_the_weight_tapers_rather_than_cutting_off():
    window = window_for_band("fresh", CONFIG)  # 0 to 12 hours
    just_outside = weight_at_lag(13.0, window, CONFIG)
    further = weight_at_lag(16.0, window, CONFIG)

    assert just_outside < 1.0, "outside the window is downweighted"
    assert further < just_outside, "and falls monotonically with distance"
    assert just_outside > 0.8, "an hour outside the band is barely less plausible than an hour inside"


def test_the_weight_never_reaches_zero():
    """The age band is heuristic. Like F6 it downweights and must never
    be able to clear a vessel on its own, which a zero weight would do:
    it would erase that vessel's field integral entirely."""
    window = window_for_band("fresh", CONFIG)
    assert weight_at_lag(48.0, window, CONFIG) == pytest.approx(CONFIG["floor_weight"])
    assert weight_at_lag(1000.0, window, CONFIG) > 0.0


def test_an_unknown_band_weights_every_hour_equally():
    """Missing evidence must leave the scoring as it found it, not
    quietly reshape the time axis."""
    times = [ACQUIRED_AT - datetime.timedelta(hours=h) for h in range(0, 49, 6)]
    weights = field_time_weights(times, ACQUIRED_AT, "not_a_band", CONFIG)
    assert set(weights.values()) == {1.0}


def test_weights_are_keyed_by_timestep_not_position():
    times = [ACQUIRED_AT - datetime.timedelta(hours=h) for h in (0, 12, 24, 48)]
    weights = field_time_weights(times, ACQUIRED_AT, "fresh", CONFIG)
    assert set(weights.keys()) == set(times)
    # Reordering the input must not change any timestep's weight.
    reordered = field_time_weights(list(reversed(times)), ACQUIRED_AT, "fresh", CONFIG)
    assert weights == reordered


def test_a_fresh_slick_favours_recent_timesteps_over_distant_ones():
    times = [ACQUIRED_AT - datetime.timedelta(hours=h) for h in (2, 8, 24, 44)]
    w = field_time_weights(times, ACQUIRED_AT, "fresh", CONFIG)
    ordered = [w[t] for t in times]
    assert ordered == sorted(ordered, reverse=True), "weight must fall as the lag grows"
    assert ordered[0] == pytest.approx(1.0)
    assert ordered[-1] == pytest.approx(CONFIG["floor_weight"])


def test_a_weathered_slick_favours_distant_timesteps_over_recent_ones():
    """The inverse of the fresh case, and the reason this is evidence
    rather than a recency prior dressed up as physics."""
    times = [ACQUIRED_AT - datetime.timedelta(hours=h) for h in (2, 8, 24, 44)]
    w = field_time_weights(times, ACQUIRED_AT, "weathered", CONFIG)
    ordered = [w[t] for t in times]
    assert ordered == sorted(ordered), "weight must rise as the lag grows"
    assert ordered[0] == pytest.approx(CONFIG["floor_weight"])
    assert ordered[-1] == pytest.approx(1.0)


def test_a_timestep_after_acquisition_is_not_extrapolated():
    """The field's gridding adds half a bin past the last sample, so a
    timestep can sit marginally after acquisition. It is not an origin
    in the future; it must be treated as the nearest thing to zero lag."""
    after = ACQUIRED_AT + datetime.timedelta(minutes=16)
    w = field_time_weights([after], ACQUIRED_AT, "fresh", CONFIG)
    assert w[after] == pytest.approx(1.0)


def test_describe_window_states_it_is_a_band_not_an_age():
    text = describe_window("fresh", CONFIG)
    assert "0 and 12 hours" in text
    assert "not an estimate of its age in hours" in text


def test_defaults_apply_when_no_config_is_given():
    window = window_for_band("fresh")
    assert window == (0.0, 12.0)
    assert weight_at_lag(100.0, window) == pytest.approx(DEFAULT_FLOOR_WEIGHT)


def test_weighted_span_reports_how_much_of_the_horizon_is_favoured():
    times = [ACQUIRED_AT - datetime.timedelta(hours=h) for h in range(0, 49)]
    fresh = weighted_span_hours(field_time_weights(times, ACQUIRED_AT, "fresh", CONFIG))
    flat = weighted_span_hours(field_time_weights(times, ACQUIRED_AT, "unknown", CONFIG))
    assert fresh < flat, "a band that favours part of the horizon must total less than a flat one"
