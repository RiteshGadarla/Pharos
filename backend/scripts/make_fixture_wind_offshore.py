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
HOURS_AFTER = 6
TIMES = ACQUIRED_AT + np.arange(-HOURS_BEFORE, HOURS_AFTER + 1) * np.timedelta64(1, "h")

LATS = np.round(np.arange(16.0, 18.01, 0.05), 3)
LONS = np.round(np.arange(67.0, 69.01, 0.05), 3)

# A steady moderate wind, within the wind gate's own valid window, so
# there is nothing gate-specific being tested here, just a plausible
# windage term for the drift model.
WIND_U, WIND_V = 4.0, -2.0


def make_dataset() -> xr.Dataset:
    n_times = len(TIMES)
    u10 = np.full((n_times, len(LATS), len(LONS)), WIND_U, dtype=np.float32)
    v10 = np.full((n_times, len(LATS), len(LONS)), WIND_V, dtype=np.float32)
    return xr.Dataset(
        {
            "u10": (("time", "lat", "lon"), u10, {"standard_name": "x_wind", "units": "m s-1"}),
            "v10": (("time", "lat", "lon"), v10, {"standard_name": "y_wind", "units": "m s-1"}),
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
