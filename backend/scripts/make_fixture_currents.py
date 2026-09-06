"""Generates a small synthetic, CF-compliant ocean current NetCDF for
offline tests, readable directly by OpenDrift's reader_netCDF_CF_generic.

Not real CMEMS or HYCOM data. Stands in until Copernicus Marine access
is wired up (PLAN.md section 4A). Covers the same footprint as the
other synthetic fixtures, with a mild rotational (gyre-like) pattern so
the backward ensemble has something non-trivial to integrate through,
rather than a perfectly uniform drift, and with a real time axis (an M2
tide and a slowly breathing gyre) so the operator console's current
arrows are drawing a field that actually changes rather than animating a
constant. Also carries sea surface temperature.

Run: python3 scripts/make_fixture_currents.py
"""

from __future__ import annotations

import numpy as np
import xarray as xr

OUT_PATH = "data/fixtures/synthetic_currents.nc"
ACQUIRED_AT = np.datetime64("2026-01-15T02:30:00")
# Backward ensembles run up to backward_horizon_hours (default 48h, see
# pipeline.yaml) before the acquisition time, so the forcing must cover
# that whole window. A single time snapshot is not enough: OpenDrift has
# nothing to interpolate against once the sim steps outside it.
#
# HOURS_AFTER covers the forward forecast (forecast.forward_horizon_hours,
# 24h) plus a margin. It used to be 6, which quietly clipped the forecast
# to a quarter of its configured horizon: the run just returned fewer
# steps and said nothing. run_forecast now records the achieved horizon
# against the requested one so that can never pass unnoticed again, but
# the fixture should cover the horizon in the first place.
HOURS_BEFORE = 60
HOURS_AFTER = 30
TIMES = ACQUIRED_AT + np.arange(-HOURS_BEFORE, HOURS_AFTER + 1) * np.timedelta64(1, "h")

# Open Arabian Sea, well clear of the real coastline: a 48h backward
# drift near-shore can strand every ensemble member on real land (GSHHG
# is real coastline data even for a synthetic scenario), which says
# nothing useful about the ensemble mechanism itself.
LATS = np.round(np.arange(16.0, 18.01, 0.05), 3)
LONS = np.round(np.arange(67.0, 69.01, 0.05), 3)

# Gyre centre and background drift, m/s.
CENTER_LAT, CENTER_LON = 17.0, 68.0
ROTATION_SPEED = 0.15
BACKGROUND_U, BACKGROUND_V = -0.15, -0.05  # a gentle southwestward drift

# The field used to be a single steady-state snapshot repeated across
# every timestep, which was defensible while nothing looked at it: the
# ensemble spread comes from perturbing the forcing per member
# (hindcast/ensemble.py), not from the field evolving.
#
# It stopped being defensible once the operator console started drawing
# current arrows. A frozen field animates into arrows that never move,
# which is decorative physics: the viewer reads motion into a display
# that is telling them nothing, and the provenance chip beside it would
# be claiming a real forcing source for a constant.
#
# So the time variation below is small, physical and named. It does not
# exist to make the map livelier; it exists so that what the map draws
# is a field that genuinely has a time axis.

# Semidiurnal (M2) tide, the dominant time-varying signal in shelf and
# near-shelf currents. Period 12.42 h, amplitude well below the gyre so
# the drift climatology the ensemble integrates is unchanged in
# character, only in detail.
M2_PERIOD_H = 12.4206
M2_AMPLITUDE = 0.06  # m/s
# Principal tidal axis, degrees from east. Tidal ellipses are strongly
# polarised; a rectilinear axis is the right first approximation.
M2_AXIS_DEG = 35.0

# Slow strengthening and relaxation of the gyre itself, on an inertial
# timescale. At 17 N the inertial period is about 41 h.
GYRE_MODULATION = 0.18
GYRE_PERIOD_H = 41.0

# Sea surface temperature. January in the open Arabian Sea, roughly 26
# to 27 C, cooler to the north, with a warm core over the gyre centre
# and a diurnal cycle. Oil weathering is temperature dependent, so this
# is context for the age band as well as for the drift.
SST_BASE_C = 26.6
SST_LAT_GRADIENT_C = -0.7  # per degree of latitude, northwards
SST_WARM_CORE_C = 0.6
SST_DIURNAL_C = 0.35


def _hours_from_start(times: np.ndarray) -> np.ndarray:
    return (times - times[0]) / np.timedelta64(1, "h")


def _hour_of_day(times: np.ndarray) -> np.ndarray:
    return (times - times.astype("datetime64[D]")) / np.timedelta64(1, "h")


def make_dataset() -> xr.Dataset:
    lon_grid, lat_grid = np.meshgrid(LONS, LATS)
    dx = lon_grid - CENTER_LON
    dy = lat_grid - CENTER_LAT
    r = np.sqrt(dx**2 + dy**2) + 1e-6

    # tangential (rotational) component plus a uniform background drift
    u_gyre = -ROTATION_SPEED * (dy / r)
    v_gyre = ROTATION_SPEED * (dx / r)

    hours = _hours_from_start(TIMES)
    n_times = len(TIMES)

    # Gyre strength breathes on the inertial timescale.
    gyre_gain = 1.0 + GYRE_MODULATION * np.sin(2 * np.pi * hours / GYRE_PERIOD_H)
    # Rectilinear M2 tide along a fixed principal axis, uniform in space:
    # the tidal wavelength is far longer than this 2 by 2 degree box.
    tide = M2_AMPLITUDE * np.sin(2 * np.pi * hours / M2_PERIOD_H)
    axis = np.radians(M2_AXIS_DEG)

    u = (
        gyre_gain[:, None, None] * u_gyre[None, :, :]
        + BACKGROUND_U
        + (tide * np.cos(axis))[:, None, None]
    ).astype(np.float32)
    v = (
        gyre_gain[:, None, None] * v_gyre[None, :, :]
        + BACKGROUND_V
        + (tide * np.sin(axis))[:, None, None]
    ).astype(np.float32)

    # Sea surface temperature, in Celsius. Warm core over the gyre
    # centre, cooling northwards, with a diurnal cycle peaking mid
    # afternoon local time.
    warm_core = SST_WARM_CORE_C * np.exp(-((r / 0.6) ** 2))
    sst_field = SST_BASE_C + SST_LAT_GRADIENT_C * (lat_grid - CENTER_LAT) + warm_core
    diurnal = SST_DIURNAL_C * np.sin(2 * np.pi * (_hour_of_day(TIMES) - 9.0) / 24.0)
    thetao = (sst_field[None, :, :] + diurnal[:, None, None]).astype(np.float32)

    ds = xr.Dataset(
        {
            "uo": (("time", "lat", "lon"), u, {
                "standard_name": "eastward_sea_water_velocity",
                "units": "m s-1",
            }),
            "vo": (("time", "lat", "lon"), v, {
                "standard_name": "northward_sea_water_velocity",
                "units": "m s-1",
            }),
            # CMEMS name for sea water potential temperature, so a real
            # Copernicus Marine subset drops in without a rename.
            "thetao": (("time", "lat", "lon"), thetao, {
                "standard_name": "sea_water_potential_temperature",
                "units": "degree_Celsius",
            }),
        },
        coords={
            "time": TIMES,
            "lat": ("lat", LATS, {"standard_name": "latitude", "units": "degrees_north"}),
            "lon": ("lon", LONS, {"standard_name": "longitude", "units": "degrees_east"}),
        },
        attrs={
            "source": "synthetic fixture, not real CMEMS/HYCOM data",
            "note": "PLAN.md section 4A: Copernicus Marine not yet wired up",
            "time_variation": (
                "gyre modulated on a 41 h inertial period, plus a rectilinear M2 tide "
                "(12.42 h). Small and physical, so the drawn field has a real time axis "
                "rather than being one snapshot repeated."
            ),
            "Conventions": "CF-1.8",
        },
    )
    return ds


if __name__ == "__main__":
    ds = make_dataset()
    ds.to_netcdf(OUT_PATH)
    print(f"wrote {OUT_PATH}, dims={dict(ds.sizes)}")
