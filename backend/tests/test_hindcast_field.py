"""Tests for the origin probability field. See PLAN.md section 8 and
section 16: "a test that the origin field normalises to 1 and retains
its time dimension."
"""

import datetime

import numpy as np
import pytest
import xarray as xr

from services.core.hindcast.ensemble import run_ensemble
from services.core.hindcast.field import build_origin_field, collect_samples, write_origin_field
from services.core.schemas import Detection, OriginField


def _fake_member_result(lats: list[float], lons: list[float], times: list[str], status: list[list[float]]) -> xr.Dataset:
    """Hand-built stand-in for an OpenDrift result Dataset, dims
    (trajectory, time), so collect_samples/build_origin_field can be
    unit tested without running a real simulation."""
    n_traj = len(lats)
    n_time = len(times)
    lat_arr = np.tile(np.array(lats)[:, None], (1, n_time)).astype(np.float32)
    lon_arr = np.tile(np.array(lons)[:, None], (1, n_time)).astype(np.float32)
    return xr.Dataset(
        {
            "lat": (("trajectory", "time"), lat_arr),
            "lon": (("trajectory", "time"), lon_arr),
            "status": (("trajectory", "time"), np.array(status, dtype=np.float32)),
        },
        coords={"trajectory": np.arange(n_traj), "time": np.array(times, dtype="datetime64[ns]")},
    )


def test_collect_samples_only_includes_active_particles():
    result = _fake_member_result(
        lats=[10.0, 20.0],
        lons=[70.0, 80.0],
        times=["2026-01-15T00:00:00", "2026-01-15T00:30:00"],
        status=[[0, 0], [0, 1]],  # trajectory 1 goes inactive (stranded) at the second step
    )
    lats, lons, times = collect_samples([result])
    # 2 active at t0, 1 active at t1 = 3 samples total
    assert len(lats) == 3
    assert 20.0 not in lats[times == np.datetime64("2026-01-15T00:30:00")]


def test_build_origin_field_normalises_to_one():
    result = _fake_member_result(
        lats=[10.0, 10.01, 10.02],
        lons=[70.0, 70.01, 70.02],
        times=["2026-01-15T00:00:00", "2026-01-15T00:30:00", "2026-01-15T01:00:00"],
        status=[[0, 0, 0], [0, 0, 0], [0, 0, 0]],
    )
    field_ds = build_origin_field(
        [result], grid_resolution_deg=0.01, time_step_minutes=30,
        gaussian_bandwidth_deg=0.02, seed=26143,
    )
    total = float(field_ds["probability"].values.sum())
    assert total == pytest.approx(1.0, rel=1e-6)


def test_build_origin_field_retains_a_real_time_dimension():
    result = _fake_member_result(
        lats=[10.0, 10.01],
        lons=[70.0, 70.01],
        times=["2026-01-15T00:00:00", "2026-01-15T00:30:00", "2026-01-15T01:00:00"],
        status=[[0, 0, 0], [0, 0, 0]],
    )
    field_ds = build_origin_field(
        [result], grid_resolution_deg=0.01, time_step_minutes=30,
        gaussian_bandwidth_deg=0.02, seed=26143,
    )
    assert "time" in field_ds.dims
    assert field_ds.sizes["time"] > 1
    # per-timestep slices must NOT already be collapsed/summed together,
    # non-negotiable 1: the field is never reduced to a single point/slice
    assert field_ds["probability"].isel(time=0).sum() < total_sum(field_ds)


def total_sum(field_ds):
    return float(field_ds["probability"].values.sum())


def test_build_origin_field_records_seed_and_n_members():
    result = _fake_member_result(
        lats=[10.0], lons=[70.0], times=["2026-01-15T00:00:00"], status=[[0]],
    )
    field_ds = build_origin_field(
        [result, result], grid_resolution_deg=0.01, time_step_minutes=30,
        gaussian_bandwidth_deg=0.02, seed=26143,
    )
    assert field_ds.attrs["seed"] == 26143
    assert field_ds.attrs["n_members"] == 2


def test_write_origin_field_round_trips_through_netcdf(tmp_path):
    result = _fake_member_result(
        lats=[10.0, 10.01], lons=[70.0, 70.01],
        times=["2026-01-15T00:00:00", "2026-01-15T00:30:00"],
        status=[[0, 0], [0, 0]],
    )
    field_ds = build_origin_field(
        [result], grid_resolution_deg=0.01, time_step_minutes=30,
        gaussian_bandwidth_deg=0.02, seed=26143,
    )
    out_path = str(tmp_path / "field.nc")
    origin_field = write_origin_field(field_ds, detection_id="det-1", out_path=out_path)

    assert isinstance(origin_field, OriginField)
    assert origin_field.detection_id == "det-1"
    assert origin_field.n_members == 1
    assert origin_field.seed == 26143

    reloaded = xr.open_dataset(out_path)
    assert reloaded["probability"].values.sum() == pytest.approx(1.0, rel=1e-6)


@pytest.mark.slow
def test_build_origin_field_from_a_real_small_ensemble():
    """End to end: real OpenDrift ensemble output through the same
    binning/normalisation path used in production."""
    detection = Detection(
        detection_id="det-1", scene_id="SCENE-1", class_name="oil",
        geometry={
            "type": "Polygon",
            "coordinates": [[[67.98, 16.98], [67.98, 17.02], [68.02, 17.02], [68.02, 16.98], [67.98, 16.98]]],
        },
        mean_class_prob=0.9, pixel_area=100,
    )
    config = {
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
    results = run_ensemble(
        detection, "data/fixtures/synthetic_currents.nc", "data/fixtures/synthetic_wind_offshore.nc",
        datetime.datetime(2026, 1, 15, 2, 30), config,
    )
    field_ds = build_origin_field(
        results, grid_resolution_deg=0.01, time_step_minutes=30,
        gaussian_bandwidth_deg=0.02, seed=config["seed"],
    )
    assert float(field_ds["probability"].values.sum()) == pytest.approx(1.0, rel=1e-6)
    assert field_ds.sizes["time"] > 1
