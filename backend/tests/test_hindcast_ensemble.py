"""Tests for the backward drift ensemble. See PLAN.md section 8 and
section 16 ("test that the origin field normalises to 1... test that
the rewind sequence's particle frames match the OpenDrift output
arrays" - this file covers the OpenDrift side of that guarantee).

Uses small n_members and a short horizon for speed: the ensemble
mechanism is what's under test, not full-scale physics. The offshore
synthetic fixtures (make_fixture_currents.py,
make_fixture_wind_offshore.py) keep every particle in open water so
runs complete deterministically without coastline stranding.
"""

import datetime

import numpy as np
import pytest
from shapely.geometry import Point, shape

from services.core.hindcast.ensemble import (
    run_ensemble,
    sample_member_configs,
    seed_points_in_polygon,
)
from services.core.schemas import Detection

CURRENTS_FIXTURE = "data/fixtures/synthetic_currents.nc"
WIND_FIXTURE = "data/fixtures/synthetic_wind_offshore.nc"
ACQUIRED_AT = datetime.datetime(2026, 1, 15, 2, 30)

SMALL_DETECTION = Detection(
    detection_id="det-1",
    scene_id="SCENE-1",
    class_name="oil",
    geometry={
        "type": "Polygon",
        "coordinates": [[[67.98, 16.98], [67.98, 17.02], [68.02, 17.02], [68.02, 16.98], [67.98, 16.98]]],
    },
    mean_class_prob=0.9,
    pixel_area=100,
)

SMALL_CONFIG = {
    "seed": 26143,
    "hindcast": {
        "n_members_full": 2,
        "particles_per_member": 5,
        "backward_horizon_hours": 2,
        "wind_drift_factor_range": [0.02, 0.04],
        "current_perturbation_magnitude": 0.05,
        "horizontal_diffusivity_range": [1.0, 10.0],
        "seed_time_jitter_minutes": 10,
        "field": {"time_step_minutes": 30},
    },
}


def test_seed_points_are_inside_the_polygon():
    polygon = shape(SMALL_DETECTION.geometry)
    rng = np.random.default_rng(1)
    lons, lats = seed_points_in_polygon(polygon, 20, rng)
    assert len(lons) == len(lats) == 20
    for lon, lat in zip(lons, lats):
        assert polygon.contains(Point(lon, lat))


def test_seed_points_deterministic_given_same_rng_state():
    polygon = shape(SMALL_DETECTION.geometry)
    lons_a, lats_a = seed_points_in_polygon(polygon, 10, np.random.default_rng(42))
    lons_b, lats_b = seed_points_in_polygon(polygon, 10, np.random.default_rng(42))
    assert lons_a == lons_b
    assert lats_a == lats_b


def test_member_configs_stay_within_configured_ranges():
    rng = np.random.default_rng(7)
    hindcast_cfg = SMALL_CONFIG["hindcast"]
    members = sample_member_configs(10, hindcast_cfg, rng)
    assert len(members) == 10
    wind_lo, wind_hi = hindcast_cfg["wind_drift_factor_range"]
    diff_lo, diff_hi = hindcast_cfg["horizontal_diffusivity_range"]
    jitter = hindcast_cfg["seed_time_jitter_minutes"]
    for m in members:
        assert wind_lo <= m.wind_drift_factor <= wind_hi
        assert diff_lo <= m.horizontal_diffusivity <= diff_hi
        assert -jitter <= m.seed_time_jitter_minutes <= jitter


def test_member_configs_are_not_all_identical():
    rng = np.random.default_rng(7)
    members = sample_member_configs(10, SMALL_CONFIG["hindcast"], rng)
    wind_factors = {m.wind_drift_factor for m in members}
    assert len(wind_factors) > 1  # genuinely perturbed, not a fixed constant


@pytest.fixture(scope="module")
def small_ensemble_results():
    return run_ensemble(SMALL_DETECTION, CURRENTS_FIXTURE, WIND_FIXTURE, ACQUIRED_AT, SMALL_CONFIG)


def test_run_ensemble_returns_one_result_per_member(small_ensemble_results):
    assert len(small_ensemble_results) == SMALL_CONFIG["hindcast"]["n_members_full"]
    for result in small_ensemble_results:
        assert result.sizes["trajectory"] == SMALL_CONFIG["hindcast"]["particles_per_member"]
        assert result.sizes["time"] > 1  # a real time dimension, not a single point


def test_run_ensemble_particles_move_backward_in_time(small_ensemble_results):
    result = small_ensemble_results[0]
    times = result["time"].values
    assert times[-1] < times[0]  # backward simulation: last step is earliest


def test_run_ensemble_members_diverge(small_ensemble_results):
    # different perturbed forcing per member should produce different
    # trajectories, this is the whole point of the ensemble
    final_lon_a = small_ensemble_results[0]["lon"].isel(time=-1).values
    final_lon_b = small_ensemble_results[1]["lon"].isel(time=-1).values
    assert not np.allclose(final_lon_a, final_lon_b)


def test_run_ensemble_is_deterministic_given_the_same_seed():
    results_a = run_ensemble(SMALL_DETECTION, CURRENTS_FIXTURE, WIND_FIXTURE, ACQUIRED_AT, SMALL_CONFIG)
    results_b = run_ensemble(SMALL_DETECTION, CURRENTS_FIXTURE, WIND_FIXTURE, ACQUIRED_AT, SMALL_CONFIG)
    for a, b in zip(results_a, results_b):
        np.testing.assert_array_equal(a["lat"].values, b["lat"].values)
        np.testing.assert_array_equal(a["lon"].values, b["lon"].values)
