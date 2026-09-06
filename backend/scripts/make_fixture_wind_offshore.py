"""Generates a small synthetic 10m wind NetCDF for the P6 backward drift
ensemble fixture, covering the same open-ocean domain and time range as
make_fixture_currents.py.

Not real ERA5 or GFS data. Stands in until CDS or the no-auth GFS S3
fallback is wired up (PLAN.md section 4A). A separate fixture from
synthetic_wind.nc (the wind gate's fixture): that one is scoped tightly
around the near-shore P2 detection fixture and deliberately has four
distinct wind zones, neither of which is what the ensemble needs, a
single steady, moderate wind over open water.

Run: python3 scripts/make_fixture_wind_offshore.py
"""

from __future__ import annotations

import numpy as np
import xarray as xr

OUT_PATH = "data/fixtures/synthetic_wind_offshore.nc"
ACQUIRED_AT = np.datetime64("2026-01-15T02:30:00")
HOURS_BEFORE = 60
# Must match make_fixture_currents.py: the forward forecast needs both
# forcings out to forecast.forward_horizon_hours, and the shorter of the
# two is what actually clips the run.
HOURS_AFTER = 30
TIMES = ACQUIRED_AT + np.arange(-HOURS_BEFORE, HOURS_AFTER + 1) * np.timedelta64(1, "h")

LATS = np.round(np.arange(16.0, 18.01, 0.05), 3)
LONS = np.round(np.arange(67.0, 69.01, 0.05), 3)

# A moderate wind, comfortably inside the wind gate's valid window, so
# nothing gate-specific is being tested here: this is a plausible
# windage term for the drift model and a plausible field to draw.
#
# It used to be np.full, one number for every cell at every hour. That
# was the weakest fixture in the repository. It gave the drift model a
# windage term with no structure to integrate, it gave the wind gate a
# value that could not vary with where the detection was, and once the
# console started drawing wind arrows it would have drawn a field of
# identical arrows that never moved, which is decorative physics wearing
# a provenance chip.
#
# The structure below is the northeast winter monsoon over the Arabian
# Sea: a steady background flow, a broad synoptic gradient across the
# box, a slow veer over the three day window, and a diurnal component.
# All small enough that the gate verdict and the ensemble's character
# are unchanged, all large enough to be a real field rather than a
# constant.
# Speed 5.25 m/s on the same bearing the constant field used. Raised
# from 4.47 so that once the diurnal term is subtracted at the 02:30 UTC
# acquisition (pre-dawn locally, the daily minimum) the wind at the slick
# still lands near 4.5 m/s, comfortably clear of the gate's downgrade
# band at 3.5. The old constant had no diurnal term to be clear of.
WIND_U, WIND_V = 4.70, -2.35

# Broad synoptic gradient across the 2 by 2 degree box: wind freshens
# towards the north, where the pressure gradient is tighter.
WIND_LAT_GRADIENT = 0.55  # m/s per degree of latitude
WIND_LON_GRADIENT = -0.25

# Slow veer of the whole pattern over the window, degrees per hour. A
# synoptic system takes days to cross, so a few degrees an hour is the
# right order.
VEER_DEG_PER_HOUR = 0.22

# Diurnal component, strengthening in the afternoon.
DIURNAL_AMPLITUDE = 0.8  # m/s

# 2 m air temperature. January over the open Arabian Sea: a little
# cooler than the sea surface, cooling northwards, with a diurnal range
# damped by the ocean underneath.
T2M_BASE_C = 24.8
T2M_LAT_GRADIENT_C = -0.9  # per degree of latitude, northwards
T2M_DIURNAL_C = 1.6

CENTER_LAT, CENTER_LON = 17.0, 68.0


def _hours_from_start(times: np.ndarray) -> np.ndarray:
    return (times - times[0]) / np.timedelta64(1, "h")


def _hour_of_day(times: np.ndarray) -> np.ndarray:
    return (times - times.astype("datetime64[D]")) / np.timedelta64(1, "h")


def make_dataset() -> xr.Dataset:
    lon_grid, lat_grid = np.meshgrid(LONS, LATS)
    dlat = lat_grid - CENTER_LAT
    dlon = lon_grid - CENTER_LON

    hours = _hours_from_start(TIMES)
    hod = _hour_of_day(TIMES)

    base_speed = float(np.hypot(WIND_U, WIND_V))
    base_dir = np.arctan2(WIND_V, WIND_U)

    # Speed: background, plus a synoptic gradient across the box, plus a
    # diurnal term peaking mid afternoon LOCAL, which at 68 E is UTC plus
    # about 4.5 hours. Using UTC directly would put the daily maximum in
    # the wrong place by a fifth of a cycle.
    solar_hour = (hod + CENTER_LON / 15.0) % 24.0
    speed_field = base_speed + WIND_LAT_GRADIENT * dlat + WIND_LON_GRADIENT * dlon
    diurnal = DIURNAL_AMPLITUDE * np.sin(2 * np.pi * (solar_hour - 15.0) / 24.0)
    speed = speed_field[None, :, :] + diurnal[:, None, None]
    # The gate treats calm as ambiguous and gale as breakup; neither is
    # what this fixture is for, so keep it off both rails.
    speed = np.clip(speed, 3.0, 9.5)

    # Direction: the whole pattern veers slowly, and backs slightly to
    # the north, so the field is not merely a rotating constant.
    direction = (
        base_dir
        + np.radians(VEER_DEG_PER_HOUR * hours)[:, None, None]
        + np.radians(6.0 * dlat)[None, :, :]
    )

    u10 = (speed * np.cos(direction)).astype(np.float32)
    v10 = (speed * np.sin(direction)).astype(np.float32)

    t2m_field = T2M_BASE_C + T2M_LAT_GRADIENT_C * dlat
    t2m_diurnal = T2M_DIURNAL_C * np.sin(2 * np.pi * (solar_hour - 15.0) / 24.0)
    t2m = (t2m_field[None, :, :] + t2m_diurnal[:, None, None]).astype(np.float32)

    return xr.Dataset(
        {
            "u10": (("time", "lat", "lon"), u10, {"standard_name": "x_wind", "units": "m s-1"}),
            "v10": (("time", "lat", "lon"), v10, {"standard_name": "y_wind", "units": "m s-1"}),
            # ERA5 name for 2 m air temperature, so a real CDS subset
            # drops in without a rename. Celsius here, not Kelvin, and
            # the units attribute says so.
            "t2m": (("time", "lat", "lon"), t2m, {
                "standard_name": "air_temperature",
                "units": "degree_Celsius",
            }),
        },
        coords={
            "time": TIMES,
            "lat": ("lat", LATS, {"standard_name": "latitude", "units": "degrees_north"}),
            "lon": ("lon", LONS, {"standard_name": "longitude", "units": "degrees_east"}),
        },
        attrs={
            "source": "synthetic fixture, not real ERA5/GFS data",
            "note": "PLAN.md section 4A: CDS/GFS not yet wired up",
            "Conventions": "CF-1.8",
        },
    )


if __name__ == "__main__":
    ds = make_dataset()
    ds.to_netcdf(OUT_PATH)
    print(f"wrote {OUT_PATH}, dims={dict(ds.sizes)}")
