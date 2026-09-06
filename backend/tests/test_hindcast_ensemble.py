"""Tests for the backward drift ensemble. See PLAN.md section 9 and
section 21 ("test that the origin field normalises to 1... test that
the rewind sequence's particle frames match the OpenDrift output
arrays" - this file covers the OpenDrift side of that guarantee).

run_ensemble returns one (n_particles, n_steps, 3) array of lat, lon
and epoch seconds per member, whichever DriftKernel produced it. That
uniform shape is what lets every stage downstream of the kernel work
unchanged when the kernel is swapped, so it is what these tests assert
against rather than any one kernel's own result object.

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


def test_run_ensemble_returns_one_sample_array_per_member(small_ensemble_results):
    assert len(small_ensemble_results) == SMALL_CONFIG["hindcast"]["n_members_full"]
    for samples in small_ensemble_results:
        assert samples.ndim == 3
        assert samples.shape[0] == SMALL_CONFIG["hindcast"]["particles_per_member"]
        assert samples.shape[1] > 1  # a real time dimension, not a single point
        assert samples.shape[2] == 3  # lat, lon, time


def test_run_ensemble_particles_move_backward_in_time(small_ensemble_results):
    times = small_ensemble_results[0][0, :, 2]
    assert times[-1] < times[0]  # backward simulation: last step is earliest


def test_run_ensemble_members_diverge(small_ensemble_results):
    # different perturbed forcing per member should produce different
    # trajectories, this is the whole point of the ensemble
    final_lon_a = small_ensemble_results[0][:, -1, 1]
    final_lon_b = small_ensemble_results[1][:, -1, 1]
    assert not np.allclose(final_lon_a, final_lon_b)


def test_run_ensemble_is_deterministic_given_the_same_seed():
    results_a = run_ensemble(SMALL_DETECTION, CURRENTS_FIXTURE, WIND_FIXTURE, ACQUIRED_AT, SMALL_CONFIG)
    results_b = run_ensemble(SMALL_DETECTION, CURRENTS_FIXTURE, WIND_FIXTURE, ACQUIRED_AT, SMALL_CONFIG)
    for a, b in zip(results_a, results_b):
        np.testing.assert_array_equal(a, b)


def test_the_null_kernel_runs_the_same_ensemble_with_no_forcing_at_all():
    """The architecture claim, tested. The null kernel takes no forcing
    data, so it also proves the ensemble machinery does not secretly
    depend on OpenDrift being reachable."""
    from services.core.drift.null import NullKernel

    results = run_ensemble(
        SMALL_DETECTION, "does/not/exist.nc", "does/not/exist.nc", ACQUIRED_AT,
        SMALL_CONFIG, kernel=NullKernel(),
    )
    assert len(results) == SMALL_CONFIG["hindcast"]["n_members_full"]
    for samples in results:
        assert samples.shape[0] == SMALL_CONFIG["hindcast"]["particles_per_member"]
        assert samples.shape[1] > 1
        # nothing moved: every particle holds its seed position
        assert np.allclose(samples[:, 0, 0], samples[:, -1, 0])
        assert np.allclose(samples[:, 0, 1], samples[:, -1, 1])
        # but time still ran backwards, so the field keeps a real time axis
        assert samples[0, -1, 2] < samples[0, 0, 2]


def test_kernel_selection_comes_from_config():
    from services.core.drift.null import NullKernel
    from services.core.hindcast.ensemble import resolve_kernel

    assert resolve_kernel({"hindcast": {"kernel": "null"}}).name == "null"
    assert resolve_kernel({"hindcast": {"kernel": "openoil"}}).name == "openoil"
    assert resolve_kernel({"hindcast": {}}).name == "openoil"  # default
    assert isinstance(resolve_kernel({"hindcast": {"kernel": "null"}}), NullKernel)

    with pytest.raises(ValueError, match="unknown drift kernel"):
        resolve_kernel({"hindcast": {"kernel": "teleportation"}})
