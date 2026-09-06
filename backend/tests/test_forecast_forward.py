"""Tests for the forward forecast. See PLAN.md section 15.

Two things are being defended here. That the forward run is genuinely
the same engine as the backward one, seeded from the same particles
under the same sampled physics, so the two halves of the drift picture
meet at acquisition. And that a forecast field can never be scored: it
has the same dims and dtype as the origin field, so nothing but an
explicit check stands between a substitution and a silently wrong
accusation.
"""

import datetime

import numpy as np
import pytest
import xarray as xr

from services.core.drift.null import NullKernel
from services.core.forecast.forward import (
    assert_not_scoring_input,
    forecast_config,
    horizon_note,
    is_forecast,
    reachable_mass_within,
    run_forecast,
)
from services.core.hindcast.ensemble import run_ensemble
from services.core.hindcast.field import build_origin_field
from services.core.schemas import Detection, OriginField

DETECTION = Detection(
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

ACQUIRED_AT = datetime.datetime(2026, 1, 15, 2, 30)

CONFIG = {
    "seed": 26143,
    "hindcast": {
        "n_members_full": 2,
        "particles_per_member": 5,
        "backward_horizon_hours": 4,
        "wind_drift_factor_range": [0.02, 0.04],
        "current_perturbation_range": [0.05, 0.15],
        "horizontal_diffusivity_range": [1.0, 10.0],
        "seed_time_jitter_minutes": 10,
        "field": {
            "grid_resolution_deg": 0.01,
            "time_step_minutes": 30,
            "gaussian_bandwidth_deg": 0.02,
        },
    },
    "forecast": {"forward_horizon_hours": 6, "n_members": 2},
}


# The null kernel throughout: it needs no forcing files and no OpenDrift
# install, and it is the kernel that proves direction is a property of
# the run rather than of any one physics package. See PLAN.md 9.1.
KERNEL = NullKernel()


def _run(direction: str, horizon: float) -> list[np.ndarray]:
    return run_ensemble(
        DETECTION, "unused.nc", "unused.nc", ACQUIRED_AT, CONFIG,
        n_members=2, kernel=KERNEL, direction=direction, horizon_hours=horizon,
    )


def test_forward_and_backward_start_from_the_same_seed_particles():
    """The two directions must be two views of one slick, not two
    independently seeded runs that happen to share a map."""
    back = _run("backward", 4)
    fwd = _run("forward", 6)

    for b, f in zip(back, fwd):
        # (n_particles, n_steps, 3) of lat, lon, epoch seconds. Step 0 is
        # the seed position in both directions.
        np.testing.assert_allclose(b[:, 0, :2], f[:, 0, :2])


def test_forward_run_moves_time_forwards():
    fwd = _run("forward", 6)
    times = fwd[0][0, :, 2]
    assert np.all(np.diff(times) > 0)
    assert times[-1] - times[0] == pytest.approx(6 * 3600, rel=0.05)


def test_backward_run_still_moves_time_backwards():
    back = _run("backward", 4)
    times = back[0][0, :, 2]
    assert np.all(np.diff(times) < 0)


def test_a_forward_run_without_a_horizon_is_refused():
    """A forecast horizon is a response planning decision. Silently
    borrowing the 48 hour evidentiary hindcast horizon would produce a
    forecast nobody chose."""
    with pytest.raises(ValueError, match="explicit horizon_hours"):
        run_ensemble(
            DETECTION, "unused.nc", "unused.nc", ACQUIRED_AT, CONFIG,
            n_members=2, kernel=KERNEL, direction="forward",
        )


def test_unknown_direction_is_refused():
    with pytest.raises(ValueError, match="backward.*forward"):
        run_ensemble(
            DETECTION, "unused.nc", "unused.nc", ACQUIRED_AT, CONFIG,
            n_members=2, kernel=KERNEL, direction="sideways", horizon_hours=1,
        )


def test_forecast_field_normalises_to_one_and_keeps_its_time_dimension():
    field_ds = run_forecast(DETECTION, "unused.nc", "unused.nc", ACQUIRED_AT, CONFIG, kernel=KERNEL)
    assert float(field_ds["probability"].values.sum()) == pytest.approx(1.0, rel=1e-6)
    assert field_ds.sizes["time"] > 1


def test_forecast_field_is_labelled_forward():
    field_ds = run_forecast(DETECTION, "unused.nc", "unused.nc", ACQUIRED_AT, CONFIG, kernel=KERNEL)
    assert field_ds.attrs["direction"] == "forward"
    assert is_forecast(field_ds)
    assert "Never an input to attribution" in field_ds.attrs["description"]


def test_an_origin_field_is_not_a_forecast():
    back = _run("backward", 4)
    field_ds = build_origin_field(
        back, grid_resolution_deg=0.01, time_step_minutes=30,
        gaussian_bandwidth_deg=0.02, seed=26143,
    )
    assert field_ds.attrs["direction"] == "backward"
    assert not is_forecast(field_ds)
    assert_not_scoring_input(field_ds)  # must not raise


def test_a_field_with_no_direction_recorded_reads_as_backward():
    """Fields hand-built in a test, and any written before the flag
    existed, are origin fields. Only an explicit forward is a forecast."""
    bare = xr.Dataset({"probability": (("time",), np.array([1.0]))})
    assert not is_forecast(bare)
    assert_not_scoring_input(bare)


def test_a_forecast_field_cannot_be_used_where_the_origin_field_belongs():
    field_ds = run_forecast(DETECTION, "unused.nc", "unused.nc", ACQUIRED_AT, CONFIG, kernel=KERNEL)
    with pytest.raises(ValueError, match="response planning product"):
        assert_not_scoring_input(field_ds)


def test_the_scoring_engine_refuses_a_forecast_field():
    """The guard has to sit inside score_vessels, not merely be
    available for a caller to remember."""
    from services.core.scoring.engine import score_vessels

    field_ds = run_forecast(DETECTION, "unused.nc", "unused.nc", ACQUIRED_AT, CONFIG, kernel=KERNEL)
    with pytest.raises(ValueError, match="response planning product"):
        score_vessels([], field_ds, None, {"factors": {}})


def test_origin_field_record_carries_the_direction(tmp_path):
    from services.core.hindcast.field import write_origin_field

    field_ds = run_forecast(DETECTION, "unused.nc", "unused.nc", ACQUIRED_AT, CONFIG, kernel=KERNEL)
    record = write_origin_field(field_ds, "det-1", str(tmp_path / "forecast.nc"))
    assert isinstance(record, OriginField)
    assert record.direction == "forward"


def test_reachable_mass_within_is_a_fraction_that_grows_with_the_window():
    field_ds = run_forecast(DETECTION, "unused.nc", "unused.nc", ACQUIRED_AT, CONFIG, kernel=KERNEL)
    early = reachable_mass_within(field_ds, 2)
    late = reachable_mass_within(field_ds, 6)
    assert 0.0 <= early <= late <= 1.0 + 1e-9
    assert late == pytest.approx(1.0, abs=1e-6)


def test_the_reported_horizon_is_the_run_not_the_binned_axis():
    """The reported horizon must equal the horizon that was run.

    The grid's time coordinate cannot be trusted for this: it holds bin
    centres and, depending on where the kernel's steps fall relative to
    the bin edges, can run up to a step past the last sample. On the
    real 24 hour demo forecast that difference reports the run as 25
    hours, and a caption reading the axis inherits the overclaim.
    """
    field_ds = run_forecast(DETECTION, "unused.nc", "unused.nc", ACQUIRED_AT, CONFIG, kernel=KERNEL)
    requested = CONFIG["forecast"]["forward_horizon_hours"]

    assert field_ds.attrs["horizon_hours"] == pytest.approx(requested, abs=1e-6)
    assert field_ds.attrs["achieved_horizon_hours"] == pytest.approx(requested, abs=1e-6)
    assert field_ds.attrs["requested_horizon_hours"] == pytest.approx(requested, abs=1e-6)


def test_a_full_horizon_run_is_not_flagged_as_truncated():
    field_ds = run_forecast(DETECTION, "unused.nc", "unused.nc", ACQUIRED_AT, CONFIG, kernel=KERNEL)
    assert not int(field_ds.attrs["horizon_truncated"])
    assert horizon_note(field_ds) == "6 hour forecast horizon."


def test_a_short_run_is_reported_as_short():
    """A kernel that runs out of forcing stops quietly. The note has to
    say so rather than repeat the horizon that was asked for."""
    short = {**CONFIG, "forecast": {"forward_horizon_hours": 24, "n_members": 2}}
    members = _run("forward", 6)
    field_ds = build_origin_field(
        members, grid_resolution_deg=0.01, time_step_minutes=30,
        gaussian_bandwidth_deg=0.02, seed=26143, direction="forward",
    )
    field_ds.attrs["requested_horizon_hours"] = float(short["forecast"]["forward_horizon_hours"])
    field_ds.attrs["achieved_horizon_hours"] = 6.0
    field_ds.attrs["horizon_truncated"] = 1

    note = horizon_note(field_ds)
    assert "6 hour" in note
    assert "24" in note
    assert "forcing data ends" in note


def test_forecast_config_defaults_the_horizon():
    assert forecast_config({})["forward_horizon_hours"] == pytest.approx(24.0)
    assert forecast_config(CONFIG)["forward_horizon_hours"] == pytest.approx(6)
