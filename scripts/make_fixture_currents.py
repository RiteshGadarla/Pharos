"""Generates a small synthetic, CF-compliant ocean current NetCDF for
offline tests, readable directly by OpenDrift's reader_netCDF_CF_generic.

Not real CMEMS or HYCOM data. Stands in until Copernicus Marine access
is wired up (PLAN.md section 4A). Covers the same footprint as the
other synthetic fixtures, with a mild rotational (gyre-like) pattern so
the backward ensemble has something non-trivial to integrate through,
rather than a perfectly uniform drift.

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
HOURS_BEFORE = 60
HOURS_AFTER = 6
TIMES = ACQUIRED_AT + np.arange(-HOURS_BEFORE, HOURS_AFTER + 1) * np.timedelta64(1, "h")

# Open Arabian Sea, well clear of the real coastline: a 48h backward
# drift near-shore can strand every ensemble member on real land (GSHHG
# is real coastline data even for a synthetic scenario), which says
# nothing useful about the ensemble mechanism itself.
LATS = np.round(np.arange(16.0, 18.01, 0.05), 3)
LONS = np.round(np.arange(67.0, 69.01, 0.05), 3)

# gyre center and background drift, m/s. Static in time: a steady-state
# field is a reasonable synthetic simplification, the ensemble spread
# comes from perturbing the forcing per member (hindcast/ensemble.py),
# not from the field itself changing shape over time.
CENTER_LAT, CENTER_LON = 17.0, 68.0
ROTATION_SPEED = 0.15
BACKGROUND_U, BACKGROUND_V = -0.15, -0.05  # a gentle southwestward drift


def make_dataset() -> xr.Dataset:
    lon_grid, lat_grid = np.meshgrid(LONS, LATS)
    dx = lon_grid - CENTER_LON
    dy = lat_grid - CENTER_LAT
    r = np.sqrt(dx**2 + dy**2) + 1e-6

    # tangential (rotational) component plus a uniform background drift
    u = -ROTATION_SPEED * (dy / r) + BACKGROUND_U
    v = ROTATION_SPEED * (dx / r) + BACKGROUND_V

    n_times = len(TIMES)
    u = np.repeat(u[np.newaxis, :, :], n_times, axis=0).astype(np.float32)
    v = np.repeat(v[np.newaxis, :, :], n_times, axis=0).astype(np.float32)

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
        },
        coords={
            "time": TIMES,
            "lat": ("lat", LATS, {"standard_name": "latitude", "units": "degrees_north"}),
            "lon": ("lon", LONS, {"standard_name": "longitude", "units": "degrees_east"}),
        },
        attrs={
            "source": "synthetic fixture, not real CMEMS/HYCOM data",
            "note": "PLAN.md section 4A: Copernicus Marine not yet wired up",
            "Conventions": "CF-1.8",
        },
    )
    return ds


if __name__ == "__main__":
    ds = make_dataset()
    ds.to_netcdf(OUT_PATH)
    print(f"wrote {OUT_PATH}, dims={dict(ds.sizes)}")
