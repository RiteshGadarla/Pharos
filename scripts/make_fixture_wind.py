"""Generates a small synthetic 10m wind NetCDF for offline tests.

Not real ERA5 or GFS data. Stands in until CDS or the no-auth GFS S3
fallback is wired up (PLAN.md section 4A). Covers the same footprint as
data/fixtures/synthetic_scene.tif with four deliberately distinct wind
zones by longitude, so gate/wind.py's four verdict branches
(suppress-low, downgrade, accept, suppress-high) are all exercised by a
single fixture:

  lon < 72.5          : 1.5 m/s  (below wind_min, suppress)
  72.5 <= lon < 72.9   : 3.0 m/s  (within the downgrade margin)
  72.9 <= lon < 73.2   : 6.0 m/s  (accept)
  lon >= 73.2          : 13.0 m/s (above wind_max, suppress)

Run: python3 scripts/make_fixture_wind.py
"""

from __future__ import annotations

import numpy as np
import xarray as xr

OUT_PATH = "data/fixtures/synthetic_wind.nc"
ACQUIRED_AT = "2026-01-15T02:30:00"

LATS = np.round(np.arange(19.0, 20.01, 0.1), 2)
LONS = np.round(np.arange(72.0, 73.51, 0.1), 2)


def zone_speed(lon: float) -> float:
    if lon < 72.5:
        return 1.5
    if lon < 72.9:
        return 3.0
    if lon < 73.2:
        return 6.0
    return 13.0


def make_dataset() -> xr.Dataset:
    u10 = np.zeros((1, len(LATS), len(LONS)), dtype=np.float32)
    v10 = np.zeros((1, len(LATS), len(LONS)), dtype=np.float32)
    for j, lon in enumerate(LONS):
        speed = zone_speed(lon)
        u10[0, :, j] = speed  # eastward component only, v = 0
    return xr.Dataset(
        {
            "u10": (("time", "lat", "lon"), u10),
            "v10": (("time", "lat", "lon"), v10),
        },
        coords={
            "time": [np.datetime64(ACQUIRED_AT)],
            "lat": LATS,
            "lon": LONS,
        },
        attrs={
            "source": "synthetic fixture, not real ERA5/GFS data",
            "note": "PLAN.md section 4A: CDS/GFS not yet wired up",
        },
    )


if __name__ == "__main__":
    ds = make_dataset()
    ds.to_netcdf(OUT_PATH)
    print(f"wrote {OUT_PATH}, dims={dict(ds.sizes)}")
