"""Generates the wind gate's unit test fixture, a small synthetic 10 m
wind NetCDF.

Not real ERA5 or GFS data. Covers a near-shore test box with four
deliberately distinct wind zones by longitude, so gate/wind.py's four
verdict branches (suppress-low, downgrade, accept, suppress-high) are all
exercised by a single fixture:

  lon < 72.5          : about 1.5 m/s  (below wind_min, suppress)
  72.5 <= lon < 72.9   : about 3.0 m/s  (within the downgrade margin)
  72.9 <= lon < 73.2   : about 6.0 m/s  (accept)
  lon >= 73.2          : about 13.0 m/s (above wind_max, suppress)

Each zone used to be one constant eastward value at every cell and every
hour. It now carries natural texture from scripts/synthetic_metocean.py:
a spatially correlated speed field and a slowly wandering direction, both
varying in time. The texture is clipped to a band inside each zone's
verdict range, so the zone a test samples still decides the verdict and
the tests in tests/test_gate_wind.py keep testing the gate rather than
the noise. Values are illustrative, not a reanalysis.

This grid intentionally does not extend into the drift ensemble's
open-ocean domain (see make_fixture_currents.py): the wind gate only ever
samples a single detection centroid, so it does not need the coastline
clearance the backward drift ensemble does.

Run: python3 scripts/make_fixture_wind.py
"""

from __future__ import annotations

import datetime
import os
import sys

import numpy as np
import xarray as xr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import synthetic_metocean  # noqa: E402

OUT_PATH = "data/fixtures/synthetic_wind.nc"
ACQUIRED_AT = datetime.datetime(2026, 1, 15, 2, 30)
SEED = 26143
# Backward ensembles run up to backward_horizon_hours (default 48h, see
# pipeline.yaml) before the acquisition time, so the forcing must cover
# that whole window, not just the acquisition instant.
HOURS_BEFORE = 60
HOURS_AFTER = 6
TIMES = synthetic_metocean.default_times(ACQUIRED_AT, HOURS_BEFORE, HOURS_AFTER)

LATS = np.round(np.arange(19.0, 20.01, 0.1), 2)
LONS = np.round(np.arange(72.0, 73.51, 0.1), 2)

# (lon_min, nominal m/s, band low, band high). Each band stays inside its
# verdict range under config/pipeline.yaml's wind_gate: below 2.5,
# 2.5 to 3.5, 3.5 to 11.0, above 11.0.
ZONES = [
    (72.0, 1.5, 1.0, 2.1),
    (72.5, 3.0, 2.7, 3.3),
    (72.9, 6.0, 5.0, 7.0),
    (73.2, 13.0, 12.0, 14.5),
]


def zone_speed(lon: float) -> float:
    """The zone's nominal speed at this longitude."""
    return [z for z in ZONES if lon >= z[0] - 1e-9][-1][1]


def make_dataset() -> xr.Dataset:
    u10, v10 = synthetic_metocean.gate_zone_wind(ZONES, LATS, LONS, TIMES, SEED)
    return xr.Dataset(
        {
            "u10": (("time", "lat", "lon"), u10, {"standard_name": "x_wind", "units": "m s-1"}),
            "v10": (("time", "lat", "lon"), v10, {"standard_name": "y_wind", "units": "m s-1"}),
        },
        coords={
            "time": TIMES.astype("datetime64[ns]"),
            "lat": ("lat", LATS, {"standard_name": "latitude", "units": "degrees_north"}),
            "lon": ("lon", LONS, {"standard_name": "longitude", "units": "degrees_east"}),
        },
        attrs={
            "source": "synthetic fixture, not real ERA5/GFS data",
            "note": "Wind gate unit fixture: four speed zones with natural texture clipped inside each zone's band.",
            "Conventions": "CF-1.8",
        },
    )


if __name__ == "__main__":
    ds = make_dataset()
    ds.to_netcdf(OUT_PATH)
    print(f"wrote {OUT_PATH}, dims={dict(ds.sizes)}")
