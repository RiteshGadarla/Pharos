"""The forcing the console draws must be the forcing the drift ran on.

See PLAN.md 16A: every moving thing on screen must be real data. These
tests defend the two ways that can quietly stop being true. The values
must be subsampled rather than resampled, so no arrow shows a number the
forcing file never held. And the fields must genuinely vary in time and
space, because a constant field animated into arrows is a display that
tells the viewer nothing while appearing to tell them something.
"""

import datetime

import numpy as np
import pytest
import xarray as xr

from services.core.forcing import sample_at, subsample_forcing

CURRENTS = "data/fixtures/synthetic_currents.nc"
WIND = "data/fixtures/synthetic_wind_offshore.nc"
T_MIN = datetime.datetime(2026, 1, 13, 2, 30)
T_MAX = datetime.datetime(2026, 1, 15, 2, 30)


@pytest.fixture(scope="module")
def forcing() -> dict:
    return subsample_forcing(CURRENTS, WIND, T_MIN, T_MAX)


def test_every_value_exists_in_the_source_file(forcing):
    """The load-bearing test. A resampled or smoothed field would put
    numbers on screen under a provenance chip naming a dataset that
    never held them."""
    ds = xr.open_dataset(CURRENTS)
    lats, lons = np.array(forcing["lat"]), np.array(forcing["lon"])
    times = np.array([np.datetime64(t) for t in forcing["time"]])

    source = ds["uo"].sel(
        time=xr.DataArray(times, dims="t"),
        lat=xr.DataArray(lats, dims="y"),
        lon=xr.DataArray(lons, dims="x"),
        method="nearest",
    ).values

    np.testing.assert_allclose(np.array(forcing["current_u"]), source, atol=1e-4)


def test_the_grid_carries_its_own_coordinates(forcing):
    """The frontend places each arrow at its own cell centre. Shipping
    values without the grid would force it to re-derive spacing, which
    silently misplaces an irregular real subset."""
    grid = np.array(forcing["current_u"])
    assert grid.shape == (len(forcing["time"]), len(forcing["lat"]), len(forcing["lon"]))


def test_the_current_field_actually_varies_in_time(forcing):
    """It used to be one snapshot repeated across every timestep. Drawn
    as arrows that is decorative physics: motion the viewer infers from
    a display that is not moving."""
    u = np.array(forcing["current_u"])
    assert u.std(axis=0).mean() > 0.0, "current is constant in time"


def test_the_wind_field_actually_varies_in_time_and_space(forcing):
    """The wind was the worse case: np.full, one number for every cell
    at every hour."""
    u = np.array(forcing["wind_u"])
    assert u.std(axis=0).mean() > 0.0, "wind is constant in time"
    assert u.std(axis=(1, 2)).mean() > 0.0, "wind is uniform in space"


def test_both_temperatures_are_present_and_physical(forcing):
    sst = np.array(forcing["sst_c"])
    air = np.array(forcing["air_temp_c"])
    # Open Arabian Sea in January. Wide bounds on purpose: this is a
    # sanity check against a unit slip (Kelvin, or a sign), not a
    # climatology assertion.
    assert 15.0 < sst.min() and sst.max() < 35.0
    assert 15.0 < air.min() and air.max() < 35.0


def test_the_payload_stays_small_enough_to_ship(forcing):
    """The bundle is loaded whole at startup with the network unplugged.
    Forcing is context, not evidence, and must not dominate it."""
    n = len(forcing["time"]) * len(forcing["lat"]) * len(forcing["lon"])
    assert n * 6 < 40_000, f"forcing payload is {n * 6} numbers, too large for the bundle"


def test_sample_at_reports_speed_and_bearing(forcing):
    reading = sample_at(forcing, 17.0, 68.0, datetime.datetime(2026, 1, 14, 12, 0))
    assert reading["current_speed"] >= 0
    assert 0.0 <= reading["current_toward_deg"] < 360.0
    assert reading["wind_speed"] > 0
    assert "sst_c" in reading and "air_temp_c" in reading


def test_bearings_use_a_towards_convention_consistently():
    """Wind is conventionally reported as the direction it blows FROM
    and current as the direction it sets TOWARDS, which is a reliable
    source of confusion. Both are reported here as towards, and the UI
    label says so."""
    forcing = {
        "time": ["2026-01-14T12:00:00"],
        "lat": [17.0],
        "lon": [68.0],
        # Due north: u=0, v=+1 points towards 0 degrees.
        "current_u": [[[0.0]]],
        "current_v": [[[1.0]]],
        # Due east: u=+1, v=0 points towards 90 degrees.
        "wind_u": [[[1.0]]],
        "wind_v": [[[0.0]]],
    }
    r = sample_at(forcing, 17.0, 68.0, datetime.datetime(2026, 1, 14, 12, 0))
    assert r["current_toward_deg"] == pytest.approx(0.0)
    assert r["wind_toward_deg"] == pytest.approx(90.0)


def test_a_window_outside_the_fixture_is_refused_loudly():
    """Silently returning an empty grid would draw no arrows and look
    like a rendering bug rather than a coverage gap."""
    with pytest.raises(ValueError, match="does not reach the requested window"):
        subsample_forcing(
            CURRENTS, WIND,
            datetime.datetime(2020, 1, 1), datetime.datetime(2020, 1, 2),
        )


def test_cropping_to_the_case_gives_a_finer_grid_than_the_whole_domain():
    """The load-bearing fix for legibility. The fixture covers two
    degrees and the case occupies a fraction of that; spending the grid
    budget on the empty majority left about six arrows across the view
    with 22 km between them, which reads as scattered marks rather than
    a flow field."""
    whole = subsample_forcing(CURRENTS, WIND, T_MIN, T_MAX)
    cropped = subsample_forcing(CURRENTS, WIND, T_MIN, T_MAX, bbox=(67.7, 16.7, 68.3, 17.3))

    whole_step = abs(whole["lat"][1] - whole["lat"][0])
    cropped_step = abs(cropped["lat"][1] - cropped["lat"][0])
    assert cropped_step < whole_step, "cropping must buy resolution, not just a smaller box"
    assert cropped["lat"][0] >= 16.6 and cropped["lat"][-1] <= 17.4


def test_a_crop_outside_the_domain_falls_back_rather_than_returning_nothing():
    """An empty grid draws no arrows, which on screen is indistinguishable
    from a rendering bug. Coverage gaps must degrade to the full domain."""
    out = subsample_forcing(CURRENTS, WIND, T_MIN, T_MAX, bbox=(100.0, 60.0, 101.0, 61.0))
    assert len(out["lat"]) > 1 and len(out["lon"]) > 1
