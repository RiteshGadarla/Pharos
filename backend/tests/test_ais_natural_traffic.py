"""The synthetic AIS has to look like a feed, not like five scripted lines.
See PLAN.md section 10 and services/core/ais/synthetic.py.

What these defend is realism that the engine has to cope with, not
realism for its own sake: irregular reporting, isolated lost reports that
must NOT read as dark gaps, measurement noise, tracks that curve under
helm rather than running ruler-straight, a crowd of ordinary traffic with
real-looking identities, and all of it reproducible from a seed.
"""

import datetime

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from services.core.ais.darkgaps import find_dark_gaps
from services.core.ais.integrity import annotate_integrity
from services.core.ais.synthetic import (
    ALL_ROLES,
    FLAG_MIDS,
    MAX_ORDINARY_GAP_FRACTION,
    build_track,
    dark_hull_target,
    generate_background_traffic,
    generate_demo_scenario,
)
from services.core.crosscheck.radar import run_cross_check

FIELD_FIXTURE = "data/fixtures/synthetic_origin_field.nc"
AIS_CONFIG = {"dark_gap_min_minutes": 20, "max_plausible_speed_kn": 30}
GROUNDS = [{"east_km": -12.0, "north_km": 8.0, "radius_km": 6.0, "n": 2}]


@pytest.fixture(scope="module")
def field_ds():
    return xr.open_dataset(FIELD_FIXTURE)


@pytest.fixture(scope="module")
def traffic(field_ds):
    return generate_background_traffic(field_ds, AIS_CONFIG, seed=7, n_lane_vessels=10, fishing_grounds=GROUNDS, n_tugs=1)


def _intervals_min(track) -> np.ndarray:
    return np.diff([p.ts.timestamp() for p in track.points]) / 60.0


def test_background_traffic_is_a_crowd_with_a_realistic_type_mix(traffic):
    assert len(traffic) == 13
    types = {t.vessel_type for t in traffic}
    assert {"fishing", "tug"} <= types
    assert len(types & {"tanker", "cargo", "passenger"}) >= 2


def test_mmsis_are_nine_digits_with_plausible_flags_and_unique(traffic):
    mmsis = [t.mmsi for t in traffic]
    assert len(set(mmsis)) == len(mmsis)
    for track in traffic:
        assert len(track.mmsi) == 9 and track.mmsi.isdigit()
        assert track.mmsi[:3] in FLAG_MIDS[track.vessel_type]
        assert not track.mmsi.startswith("419000"), "that block is reserved for the scenario roles"


def test_speeds_follow_the_vessel_type(traffic):
    median = {t.mmsi: float(np.median([p.sog for p in t.points])) for t in traffic}
    for track in traffic:
        if track.vessel_type == "fishing":
            assert median[track.mmsi] < 6.0
        if track.vessel_type in ("tanker", "cargo", "passenger"):
            assert median[track.mmsi] > 8.0


def test_reporting_is_irregular_and_never_opens_a_dark_gap_by_itself(traffic):
    """Ordinary dropouts are the thing the dark gap threshold exists to
    ignore, so the fixture has to contain them and they have to stay under
    the threshold."""
    all_intervals = np.concatenate([_intervals_min(t) for t in traffic])
    assert all_intervals.std() > 0.5, "a fixed cadence is not a feed"
    assert all_intervals.max() < AIS_CONFIG["dark_gap_min_minutes"] * MAX_ORDINARY_GAP_FRACTION + 1e-6
    for track in traffic:
        assert track.dark_gaps == []
    # At least some reports were lost: intervals well beyond the median.
    assert (all_intervals > 2.0 * np.median(all_intervals)).sum() >= 5


def test_the_dark_gap_detector_tells_a_dropout_from_a_switch_off(field_ds):
    """The same kind of vessel, one with only ordinary dropouts and one
    with its transponder off for 45 minutes: only the second is a gap."""
    t0 = pd.Timestamp(field_ds["time"].values.min()).to_pydatetime()
    waypoints = [(17.0, 67.9, t0), (17.15, 68.15, t0 + datetime.timedelta(hours=4))]
    rng = np.random.default_rng(11)
    ordinary = build_track("636000111", "cargo", waypoints, 5.0, rng, 20, 30)
    switched_off = build_track(
        "636000112", "cargo", waypoints, 5.0, np.random.default_rng(11), 20, 30,
        drop_between=(t0 + datetime.timedelta(hours=2), t0 + datetime.timedelta(hours=2, minutes=45)),
    )
    assert find_dark_gaps(ordinary.points, 20, 30) == []
    assert len(switched_off.dark_gaps) == 1
    assert switched_off.dark_gaps[0].duration_min >= 45.0


def test_reports_carry_measurement_noise_but_no_integrity_artifacts(traffic):
    """Noise at GNSS and AIS resolution must not trip the spoofing checks:
    an ordinary vessel with ordinary noise is not a position jump."""
    annotated = annotate_integrity(traffic, {})
    assert all(t.integrity_flags == [] for t in annotated)
    track = next(t for t in traffic if t.vessel_type == "tanker" or t.vessel_type == "cargo")
    headings = np.array([p.heading for p in track.points])
    cogs = np.array([p.cog for p in track.points])
    offset = (headings - cogs + 180.0) % 360.0 - 180.0
    assert np.abs(offset).max() > 0.0, "heading identical to COG everywhere is not a real report"
    assert all(float(p.sog * 10).is_integer() for p in track.points), "SOG is reported at 0.1 kn"


def test_lane_tracks_wander_and_curve_rather_than_run_ruler_straight(traffic):
    lane = [t for t in traffic if t.vessel_type in ("tanker", "cargo")]
    spreads = []
    for track in lane:
        cogs = np.array([p.cog for p in track.points[5:-5]])
        spreads.append(np.std((cogs - cogs.mean() + 180.0) % 360.0 - 180.0))
    assert max(spreads) > 0.5
    # Wander, not chaos: course over ground on a lane stays within tens of degrees.
    assert np.median(spreads) < 15.0


def test_traffic_and_scenario_are_deterministic(field_ds):
    a = generate_background_traffic(field_ds, AIS_CONFIG, seed=7, n_lane_vessels=10, fishing_grounds=GROUNDS, n_tugs=1)
    b = generate_background_traffic(field_ds, AIS_CONFIG, seed=7, n_lane_vessels=10, fishing_grounds=GROUNDS, n_tugs=1)
    assert [t.model_dump() for t in a] == [t.model_dump() for t in b]
    c = generate_background_traffic(field_ds, AIS_CONFIG, seed=8, n_lane_vessels=10, fishing_grounds=GROUNDS, n_tugs=1)
    assert [t.mmsi for t in a] != [t.mmsi for t in c]

    s1 = generate_demo_scenario(field_ds, AIS_CONFIG, seed=26143)
    s2 = generate_demo_scenario(field_ds, AIS_CONFIG, seed=26143)
    assert [t.model_dump() for t in s1] == [t.model_dump() for t in s2]


def test_roles_select_the_scenario_vessels_without_changing_what_they_mean(field_ds):
    tracks = generate_demo_scenario(field_ds, AIS_CONFIG, seed=26143, roles=["wrong_time", "dark_far"])
    assert {t.mmsi for t in tracks} == {"419000002", "419000003"}
    assert next(t for t in tracks if t.mmsi == "419000003").dark_gaps
    with pytest.raises(ValueError):
        generate_demo_scenario(field_ds, AIS_CONFIG, seed=26143, roles=["culprit", "not-a-role"])
    assert len(ALL_ROLES) == 5


def test_a_broadcasting_culprit_has_no_dark_gap_but_keeps_its_behaviour(field_ds):
    tracks = {t.mmsi: t for t in generate_demo_scenario(field_ds, AIS_CONFIG, seed=26143, culprit_dark_gap_minutes=0)}
    culprit = tracks["419000001"]
    assert culprit.dark_gaps == []
    speeds = [p.sog for p in culprit.points]
    assert min(speeds) < 0.5 * float(np.median(speeds)), "the culprit still slows to discharge"
    # The hard negatives are untouched by the culprit's setting.
    assert tracks["419000005"].dark_gaps


def test_the_dark_hull_sits_in_the_origin_field_and_matches_no_vessel(field_ds):
    acquired = pd.Timestamp(field_ds["time"].values.max()).to_pydatetime()
    tracks = generate_demo_scenario(field_ds, AIS_CONFIG, seed=26143, roles=["wrong_time", "dark_far"])
    target = dark_hull_target(field_ds, acquired - datetime.timedelta(hours=2), "TEST", offset_m=(200.0, -150.0))
    check = run_cross_check([target], tracks, field_ds, acquired, {"match_radius_m": 1500.0})
    assert [t.target_id for t in check.unmatched] == [target.target_id]
    assert check.unmatched_in_field(1e-6), "the hull must sit where the origin field has mass"
