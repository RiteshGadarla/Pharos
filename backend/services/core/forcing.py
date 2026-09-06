"""Downsamples the forcing fields into the demo bundle. See PLAN.md
sections 16 and 16A.

The console draws wind and current arrows and reports sea and air
temperature, so the forcing has to reach the frontend. It cannot go
whole: the two NetCDF files are 91 times by 41 by 41 across five
variables, which is over 750,000 numbers and would multiply the bundle
several times over for a layer that is context rather than evidence.

So it is subsampled here, on two rules.

Subsample, never smooth or interpolate. Every value the frontend draws
is a value that exists in the forcing file at a real grid point and a
real timestep. A resampled field would put numbers on screen that no
forcing dataset ever held, under a provenance chip naming the dataset,
which is the exact failure the provenance chip exists to prevent
(PLAN.md 16A: every moving thing on screen must be real data).

Carry the grid the values are actually on. The frontend places each
arrow at its own cell centre rather than assuming a regular spacing it
would have to re-derive, so a ragged or irregular real subset drops in
later without the display quietly misplacing it.
"""

from __future__ import annotations

import datetime

import numpy as np
import xarray as xr

# Arrows denser than this stop being readable on a projector and start
# being a texture. PLAN.md 16A's ambient flow shader is the layer for
# density; this is the legible, countable, hoverable version.
DEFAULT_MAX_GRID = 14
# The forcing evolves on tidal and synoptic timescales, so three-hourly
# is plenty to interpolate the scrubber against and keeps the payload
# small. The frontend picks the nearest slice.
DEFAULT_TIME_STRIDE_HOURS = 3.0


def _stride_for(n: int, target: int) -> int:
    return max(1, int(np.ceil(n / target)))


def _iso(value) -> str:
    import pandas as pd

    return pd.Timestamp(value).to_pydatetime().replace(microsecond=0).isoformat()


def subsample_forcing(
    current_path: str,
    wind_path: str,
    t_min: datetime.datetime,
    t_max: datetime.datetime,
    bbox: tuple[float, float, float, float] | None = None,
    max_grid: int = DEFAULT_MAX_GRID,
    time_stride_hours: float = DEFAULT_TIME_STRIDE_HOURS,
) -> dict:
    """Returns the forcing over [t_min, t_max] as plain JSON-able lists.

    `bbox` is (west, south, east, north) and should be the area the case
    actually occupies, not the whole forcing domain. Cropping first is
    what makes the arrows legible: the fixture covers two degrees, the
    case occupies well under one of them, and spending the whole grid
    budget on the empty majority leaves about six arrows across the view
    with 22 km between them. Cropped to the case, the same number of
    points resolves the flow at a few kilometres.

    Wind and current are read from separate files on separate grids, as
    ERA5 and CMEMS genuinely are. The wind is sampled onto the current
    grid with nearest-neighbour selection so the two share one set of
    arrow positions; nearest rather than linear for the reason in the
    module docstring.
    """
    currents = xr.open_dataset(current_path)
    wind = xr.open_dataset(wind_path)

    window = slice(np.datetime64(t_min), np.datetime64(t_max))
    currents = currents.sel(time=window)
    if currents.sizes.get("time", 0) == 0:
        raise ValueError(
            f"the current fixture covers {_iso(xr.open_dataset(current_path)['time'].values.min())} "
            f"to {_iso(xr.open_dataset(current_path)['time'].values.max())}, "
            f"which does not reach the requested window {t_min} to {t_max}"
        )

    times = currents["time"].values
    step_h = float(np.median(np.diff(times) / np.timedelta64(1, "h"))) if len(times) > 1 else 1.0
    t_stride = max(1, int(round(time_stride_hours / max(step_h, 1e-6))))

    if bbox is not None:
        west, south, east, north = bbox
        cropped = currents.sel(lat=slice(south, north), lon=slice(west, east))
        # A crop that lands outside the domain is a coverage gap, not a
        # reason to draw nothing: fall back to the full domain rather
        # than silently returning an empty grid the console would render
        # as a rendering bug.
        if cropped.sizes.get("lat", 0) >= 2 and cropped.sizes.get("lon", 0) >= 2:
            currents = cropped

    lat_stride = _stride_for(currents.sizes["lat"], max_grid)
    lon_stride = _stride_for(currents.sizes["lon"], max_grid)

    sub = currents.isel(
        time=slice(None, None, t_stride),
        lat=slice(None, None, lat_stride),
        lon=slice(None, None, lon_stride),
    )
    # The wind lands on the current grid, nearest neighbour, so both
    # layers share arrow positions and the panel can report them at one
    # point without two lookups disagreeing about where "here" is.
    wind_on_grid = wind.sel(
        time=sub["time"], lat=sub["lat"], lon=sub["lon"], method="nearest"
    )

    def grid(ds: xr.Dataset, name: str) -> list | None:
        if name not in ds:
            return None
        return np.asarray(ds[name].values, dtype=float).round(4).tolist()

    return {
        "time": [_iso(t) for t in sub["time"].values],
        "lat": [round(float(v), 4) for v in sub["lat"].values],
        "lon": [round(float(v), 4) for v in sub["lon"].values],
        # dims (time, lat, lon) throughout, matching the origin field.
        "current_u": grid(sub, "uo"),
        "current_v": grid(sub, "vo"),
        "sst_c": grid(sub, "thetao"),
        "wind_u": grid(wind_on_grid, "u10"),
        "wind_v": grid(wind_on_grid, "v10"),
        "air_temp_c": grid(wind_on_grid, "t2m"),
        "provenance": {
            "current_source": str(currents.attrs.get("source", "unspecified")),
            "wind_source": str(wind.attrs.get("source", "unspecified")),
            "grid_deg": round(float(abs(sub["lat"].values[1] - sub["lat"].values[0])), 4)
            if sub.sizes["lat"] > 1
            else None,
            "time_step_hours": round(step_h * t_stride, 2),
            "note": (
                "Subsampled from the forcing files, never resampled: every arrow is a value "
                "that exists at that grid point and that timestep. The drift ensemble reads "
                "the full-resolution fields, not this."
            ),
        },
    }


def sample_at(forcing: dict, lat: float, lon: float, when: datetime.datetime) -> dict:
    """Nearest forcing values at a point and time, for a panel readout.

    Returns speeds and bearings rather than components: a readout that
    says "0.21 m/s towards 246 degrees" is read directly off the screen,
    where u and v have to be composed in the reader's head.
    """
    if not forcing.get("time"):
        return {}

    times = np.array([np.datetime64(t) for t in forcing["time"]])
    ti = int(np.abs(times - np.datetime64(when)).argmin())
    yi = int(np.abs(np.array(forcing["lat"]) - lat).argmin())
    xi = int(np.abs(np.array(forcing["lon"]) - lon).argmin())

    def cell(name: str) -> float | None:
        block = forcing.get(name)
        return None if block is None else float(block[ti][yi][xi])

    out: dict = {"at": forcing["time"][ti], "lat": forcing["lat"][yi], "lon": forcing["lon"][xi]}
    for label, u_name, v_name in (("current", "current_u", "current_v"), ("wind", "wind_u", "wind_v")):
        u, v = cell(u_name), cell(v_name)
        if u is None or v is None:
            continue
        out[f"{label}_speed"] = round(float(np.hypot(u, v)), 3)
        # Meteorological convention differs between wind and current and
        # confuses everyone, so both are reported as the direction the
        # vector points TOWARDS, degrees clockwise from north, and the
        # UI label says "towards" in as many words.
        out[f"{label}_toward_deg"] = round(float((np.degrees(np.arctan2(u, v)) + 360.0) % 360.0), 1)
    for label, name in (("sst_c", "sst_c"), ("air_temp_c", "air_temp_c")):
        value = cell(name)
        if value is not None:
            out[label] = round(value, 2)
    return out
