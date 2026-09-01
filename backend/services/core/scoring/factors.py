"""Named evidence factors. See PLAN.md section 10.

Every factor here returns a plain float. F1 and F2 are unbounded raw
integrals (normalised across the candidate set in scoring/engine.py);
F3-F6 are already scaled to [0, 1]. None of them is a learned weight,
per non-negotiable 3: this is an explicit formula per factor, not a
trained classifier.
"""

from __future__ import annotations

import datetime
import math

import numpy as np
import xarray as xr
from shapely.geometry import shape

from services.core.ais.tracks import course_and_speed_at, median_speed_kn, position_at
from services.core.schemas import AISTrack, SlickFeatures

DEFAULT_VESSEL_PLAUSIBILITY = {
    "tanker": 1.0,
    "cargo": 0.7,
    "fishing": 0.3,
}
DEFAULT_PLAUSIBILITY_FALLBACK = 0.5

# What a log-odds-combined factor returns when it genuinely cannot be
# computed for a vessel. It has to be 0.5, since scoring/engine.py runs
# these through a logit and logit(0.5) is 0: absent evidence must add
# nothing. Returning 0.0 instead reads as the strongest possible
# evidence against, which is a different claim entirely and not one a
# missing measurement can support.
NEUTRAL_FACTOR = 0.5


def sample_field_at(field_ds: xr.Dataset, lat: float, lon: float, time: datetime.datetime) -> float:
    """Nearest-neighbour probability at (lat, lon, time). Nearest, not
    interpolated, so a factor score is always a real cell's actual mass,
    never a blended value that could exceed what any cell holds."""
    point = field_ds["probability"].sel(lat=lat, lon=lon, time=np.datetime64(time), method="nearest")
    return float(point.values)


def field_mass_in_polygon(field_ds: xr.Dataset, polygon, time: datetime.datetime) -> float:
    """Sum of probability over grid cells whose centre falls inside
    polygon, at the nearest time slice."""
    slice_ds = field_ds.sel(time=np.datetime64(time), method="nearest")
    lats = slice_ds["lat"].values
    lons = slice_ds["lon"].values
    prob = slice_ds["probability"].values  # (lat, lon)

    minx, miny, maxx, maxy = polygon.bounds
    lat_mask = (lats >= miny) & (lats <= maxy)
    lon_mask = (lons >= minx) & (lons <= maxx)
    if not lat_mask.any() or not lon_mask.any():
        return 0.0

    total = 0.0
    for yi in np.where(lat_mask)[0]:
        for xi in np.where(lon_mask)[0]:
            if polygon.contains(shape({"type": "Point", "coordinates": (float(lons[xi]), float(lats[yi]))})):
                total += float(prob[yi, xi])
    return total


def field_timesteps_in_range(field_ds: xr.Dataset, start: datetime.datetime, end: datetime.datetime) -> list[datetime.datetime]:
    import pandas as pd

    times = [pd.Timestamp(t).to_pydatetime() for t in field_ds["time"].values]
    return [t for t in times if start <= t <= end]


def compute_field_integral(track: AISTrack, field_ds: xr.Dataset) -> float:
    """F1: sum over field timesteps of P(lat_v(t), lon_v(t), t). The
    primary factor: a vessel that lingered inside a broad uncertain
    cloud should outrank one that clipped a narrow peak, which this
    integral rewards and distance-to-centroid ranking gets backwards."""
    times = [pd_ts for pd_ts in _all_field_times(field_ds)]
    total = 0.0
    for t in times:
        pos = position_at(track, t)
        if pos is None:
            continue
        lat, lon = pos
        total += sample_field_at(field_ds, lat, lon, t)
    return total


def compute_dark_overlap(track: AISTrack, field_ds: xr.Dataset) -> float:
    """F2: mass-weighted overlap between the vessel's dark periods and
    the field's probability mass. This is the factor that inverts a
    naive AIS baseline's blind spot: going dark over the likely origin
    raises this vessel's score instead of just losing its track."""
    total = 0.0
    for gap in track.dark_gaps:
        polygon = shape(gap.envelope)
        for t in field_timesteps_in_range(field_ds, gap.start, gap.end):
            total += field_mass_in_polygon(field_ds, polygon, t)
    return total


def compute_axis_alignment(track: AISTrack, field_ds: xr.Dataset, major_axis_deg: float) -> float:
    """F3: angular agreement, modulo 180 degrees, between the slick's
    major axis and the vessel's course while inside the field's
    footprint. 1.0 is perfectly aligned or exactly opposite (a
    discharge streak has no direction), 0.0 is perpendicular."""
    samples = []
    for t in _all_field_times(field_ds):
        cs = course_and_speed_at(track, t)
        if cs is None:
            continue
        cog, _ = cs
        diff_rad = math.radians(cog - major_axis_deg)
        samples.append((math.cos(2 * diff_rad) + 1) / 2.0)
    if not samples:
        return 0.0
    return float(np.mean(samples))


def compute_speed_anomaly(track: AISTrack, field_ds: xr.Dataset) -> float:
    """F4: sustained deviation below the vessel's own median transit
    speed while inside the field's footprint. 0 if it never slowed
    down, up to 1 if it was dead in the water throughout."""
    baseline = median_speed_kn(track)
    if baseline <= 0:
        return 0.0
    samples = []
    for t in _all_field_times(field_ds):
        cs = course_and_speed_at(track, t)
        if cs is None:
            continue
        _, sog = cs
        samples.append(max(0.0, (baseline - sog) / baseline))
    if not samples:
        return 0.0
    return float(np.clip(np.mean(samples), 0.0, 1.0))


def compute_course_anomaly(track: AISTrack, field_ds: xr.Dataset) -> float:
    """F5: how much the vessel's course changed across its passage
    through the field's time window, 0-1 scaled by 180 degrees.

    Sampled at the ends of the overlap between the track and the window,
    not at the window's own edges. The window is as long as the backward
    horizon (two days) while a track is hours, so the window's edges are
    usually nowhere near the vessel and asking for a course there
    returns nothing. That is how this used to fail: it returned the
    0.0 "could not compute" sentinel for every vessel, and since F5 is
    combined in log-odds space, 0.0 is not neutral but the most extreme
    value the scale has. Every vessel picked up an identical large
    negative contribution, which drowned the factors that actually
    separate them.
    """
    import pandas as pd

    times = field_ds["time"].values
    field_t_min = pd.Timestamp(times.min()).to_pydatetime()
    field_t_max = pd.Timestamp(times.max()).to_pydatetime()

    t_before = max(field_t_min, track.points[0].ts) if track.points else field_t_min
    t_after = min(field_t_max, track.points[-1].ts) if track.points else field_t_max
    if t_after <= t_before:
        return NEUTRAL_FACTOR

    before = course_and_speed_at(track, t_before)
    after = course_and_speed_at(track, t_after)
    if before is None or after is None:
        return NEUTRAL_FACTOR
    cog_before, _ = before
    cog_after, _ = after
    delta = abs(((cog_after - cog_before + 180) % 360) - 180)
    return float(np.clip(delta / 180.0, 0.0, 1.0))


def compute_vessel_plausibility(track: AISTrack, plausibility_table: dict[str, float] | None = None) -> float:
    """F6: a small prior by vessel type. Downweights only, never
    eliminates (non-negotiable-adjacent per section 10: "attributing
    pollution by vessel class alone is exactly the kind of shortcut a
    jury should attack"), which is why this must never be wired into
    scoring/eliminate.py and why its configured weight stays low."""
    table = plausibility_table or DEFAULT_VESSEL_PLAUSIBILITY
    return float(table.get(track.vessel_type, DEFAULT_PLAUSIBILITY_FALLBACK))


def _all_field_times(field_ds: xr.Dataset):
    import pandas as pd

    return [pd.Timestamp(t).to_pydatetime() for t in field_ds["time"].values]


def compute_all_factors(
    track: AISTrack,
    field_ds: xr.Dataset,
    slick_features: SlickFeatures,
    plausibility_table: dict[str, float] | None = None,
) -> dict[str, float]:
    """Raw (pre cross-vessel normalisation) factor scores for one
    vessel. field_integral and dark_overlap still need normalising
    across the whole candidate set, see scoring/engine.py."""
    return {
        "field_integral": compute_field_integral(track, field_ds),
        "dark_overlap": compute_dark_overlap(track, field_ds),
        "axis_alignment": compute_axis_alignment(track, field_ds, slick_features.major_axis_deg),
        "speed_anomaly": compute_speed_anomaly(track, field_ds),
        "course_anomaly": compute_course_anomaly(track, field_ds),
        "vessel_plausibility": compute_vessel_plausibility(track, plausibility_table),
    }
