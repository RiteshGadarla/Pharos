"""Named evidence factors. See PLAN.md section 12.

Every factor here returns a plain float. F1, F2 and F8 are raw
probability-mass quantities (combined linearly in scoring/engine.py);
F3-F7 are already scaled to [0, 1]. None of them is a learned weight,
per non-negotiable 3: this is an explicit formula per factor, not a
trained classifier.

F7 (AIS integrity) and F8 (radar confirmed dark) are the two factors
added in the current plan revision. F8 is the only factor in the model
backed by a second, independent sensor rather than by what the vessel
chose to report about itself, which is why its configured weight is the
highest in the file.
"""

from __future__ import annotations

import datetime
import math

import numpy as np
import xarray as xr
from shapely.geometry import shape

from services.core.ais.tracks import course_and_speed_at, median_speed_kn, position_at
from services.core.schemas import AISTrack, SlickFeatures
from services.core.scoring.temporal import compute_temporal_consistency

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


def compute_field_integral(
    track: AISTrack, field_ds: xr.Dataset, time_weights: dict | None = None
) -> float:
    """F1: sum over field timesteps of P(lat_v(t), lon_v(t), t). The
    primary factor: a vessel that lingered inside a broad uncertain
    cloud should outrank one that clipped a narrow peak, which this
    integral rewards and distance-to-centroid ranking gets backwards.

    `time_weights` is the origin window implied by the slick's age band
    (scoring/age_window.py), keyed by timestep. It weights each hour of
    the horizon by how plausible an origin at that hour is given how
    weathered the slick looks. None weights every hour equally, which is
    the behaviour before the age band reached the scoring engine.
    """
    times = [pd_ts for pd_ts in _all_field_times(field_ds)]
    total = 0.0
    for t in times:
        pos = position_at(track, t)
        if pos is None:
            continue
        lat, lon = pos
        weight = 1.0 if time_weights is None else time_weights.get(t, 1.0)
        total += sample_field_at(field_ds, lat, lon, t) * weight
    return total


def compute_dark_overlap(
    track: AISTrack, field_ds: xr.Dataset, time_weights: dict | None = None
) -> float:
    """F2: mass-weighted overlap between the vessel's dark periods and
    the field's probability mass. This is the factor that inverts a
    naive AIS baseline's blind spot: going dark over the likely origin
    raises this vessel's score instead of just losing its track.

    Weighted by the age band's origin window on the same terms as F1:
    going dark over the likely origin at a time the slick's condition
    does not support is weaker evidence than going dark there at a time
    it does.
    """
    total = 0.0
    for gap in track.dark_gaps:
        polygon = shape(gap.envelope)
        for t in field_timesteps_in_range(field_ds, gap.start, gap.end):
            weight = 1.0 if time_weights is None else time_weights.get(t, 1.0)
            total += field_mass_in_polygon(field_ds, polygon, t) * weight
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


def compute_ais_integrity(track: AISTrack, field_ds: xr.Dataset) -> float:
    """F7: aggregated severity of the AIS self-report inconsistencies
    found inside the origin window (ais/integrity.py).

    Aggregated as a noisy-or rather than a sum or a mean. Two
    independent flags should raise suspicion more than one does, which
    a mean does not do, but ten flags of the same kind should not run
    away to certainty, which a sum does. Noisy-or gives both: it grows
    with each flag and saturates below 1.

    Returns NEUTRAL_FACTOR when a vessel has no flags at all, because a
    clean AIS record is the ordinary case and must contribute nothing
    rather than counting as evidence of innocence.
    """
    t_min, t_max = _field_time_bounds(field_ds)
    in_window = [f for f in track.integrity_flags if t_min <= f.at <= t_max]
    if not in_window:
        return NEUTRAL_FACTOR

    survival = 1.0
    for flag in in_window:
        survival *= 1.0 - float(np.clip(flag.severity, 0.0, 1.0))
    return float(np.clip(1.0 - survival, 0.0, 1.0))


def compute_radar_confirmed_dark(track: AISTrack, field_ds: xr.Dataset, cross_check) -> tuple[float, str | None]:
    """F8: an unmatched ship target from the SAR scene itself fell inside
    this vessel's dead-reckoned dark envelope AND in a live cell of the
    origin field.

    Returns (score, target_id). The score is how central in the origin
    field that hull sat, scaled by the radar-to-AIS match confidence
    available for the scene, so a target on the field's peak counts for
    more than one clipping its edge.

    Centrality is the mass at the target's cell divided by the field's
    own peak cell mass, NOT the raw mass. Raw mass is the wrong scale
    and would silently disable this factor: the field sums to 1 over
    the whole space-time volume, so on a 98 by 38 by 35 grid the
    average cell holds under a millionth of the mass and even a target
    sitting exactly on the peak scores a number that rounds to zero
    against the other factors. Dividing by the peak asks the question
    that actually matters, which is how close to the most likely origin
    this hull was, and gives an answer on the 0 to 1 scale the weights
    in config/scoring.yaml assume.

    This is the factor that converts a dark period from an absence of
    evidence into a positive observation: a hull Sentinel-1
    photographed that AIS did not report, in the envelope the spill
    could have started in. It still never convicts alone, see the
    caveats in crosscheck/radar.py.
    """
    if cross_check is None:
        return 0.0, None
    target, mass = cross_check.support_for(track.mmsi)
    if target is None or mass <= 0:
        return 0.0, None
    peak = float(np.max(field_ds["probability"].values))
    centrality = float(np.clip(mass / peak, 0.0, 1.0)) if peak > 0 else 0.0
    if centrality <= 0:
        return 0.0, None
    # An unmatched target has no match confidence of its own by
    # definition, so the scene's own matching quality stands in: if the
    # matcher associated everything else well, an unmatched target is a
    # stronger claim than if it associated nothing.
    matched = cross_check.matched
    scene_confidence = float(np.mean([t.match_confidence for t in matched])) if matched else 0.5
    return float(centrality * scene_confidence), target.target_id


def _field_time_bounds(field_ds: xr.Dataset) -> tuple[datetime.datetime, datetime.datetime]:
    import pandas as pd

    times = field_ds["time"].values
    return pd.Timestamp(times.min()).to_pydatetime(), pd.Timestamp(times.max()).to_pydatetime()


def _all_field_times(field_ds: xr.Dataset):
    import pandas as pd

    return [pd.Timestamp(t).to_pydatetime() for t in field_ds["time"].values]


def compute_all_factors(
    track: AISTrack,
    field_ds: xr.Dataset,
    slick_features: SlickFeatures,
    plausibility_table: dict[str, float] | None = None,
    cross_check=None,
    time_weights: dict | None = None,
    acquired_at: datetime.datetime | None = None,
    age_window_config: dict | None = None,
    temporal_config: dict | None = None,
) -> tuple[dict[str, float], str | None]:
    """Raw (pre cross-vessel normalisation) factor scores for one
    vessel, and the ShipTarget id backing F8 if it fired.

    field_integral, dark_overlap and radar_confirmed_dark are literal
    probability-mass quantities, see scoring/engine.py for why those
    three are combined linearly while the rest go through a logit.

    cross_check is the RadarCrossCheck for the scene, or None when the
    scene has no ship target extraction (F8 then contributes nothing,
    which is the correct behaviour rather than a penalty).
    """
    radar_score, radar_target_id = compute_radar_confirmed_dark(track, field_ds, cross_check)
    factors = {
        # F1 and F2 are the two factors that integrate over the field's
        # time axis, so they are the two the age band's origin window
        # applies to. The rest are either time-agnostic or already
        # scoped to when the vessel was inside the field.
        "field_integral": compute_field_integral(track, field_ds, time_weights),
        "dark_overlap": compute_dark_overlap(track, field_ds, time_weights),
        "axis_alignment": compute_axis_alignment(track, field_ds, slick_features.major_axis_deg),
        "speed_anomaly": compute_speed_anomaly(track, field_ds),
        "course_anomaly": compute_course_anomaly(track, field_ds),
        "vessel_plausibility": compute_vessel_plausibility(track, plausibility_table),
        "ais_integrity": compute_ais_integrity(track, field_ds),
        "radar_confirmed_dark": radar_score,
        # F9 asks the timing question on its own, with space
        # marginalised out. F1 above already weights the time axis, but
        # it does so inside an integral over space where the timing
        # cannot be seen or argued with. See scoring/temporal.py.
        # Without acquired_at this returns 0.5, which the engine's logit
        # turns into exactly zero contribution.
        "temporal_consistency": compute_temporal_consistency(
            track, field_ds,
            slick_features.age_band if slick_features is not None else None,
            acquired_at, age_window_config, temporal_config,
        ),
    }
    return factors, radar_target_id
