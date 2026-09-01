"""Synthetic AIS traffic generator for the demo scenario. See PLAN.md
section 9.

Lane geometry, vessel type mix, speed distributions and dropout rates
should be fitted from real MarineCadastre statistics; that data isn't
available yet (PLAN.md section 4A), so this uses documented placeholder
values instead. Only the scenario shape -- one culprit, three hard
negatives, positioned relative to wherever the origin field's mass
actually is -- reflects the plan's design. Swap the distributions for
real fitted ones without touching the scenario logic or the scoring
engine that consumes it.
"""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import xarray as xr

from services.core.ais.darkgaps import find_dark_gaps
from services.core.ais.tracks import bearing_deg, great_circle_interpolate, haversine_km
from services.core.schemas import AISPoint, AISTrack

Waypoint = tuple[float, float, datetime.datetime]  # lat, lon, time


def field_peak(field_ds: xr.Dataset) -> tuple[float, float, datetime.datetime]:
    """Returns (lat, lon, time) of the origin field's single highest-mass
    cell. Orientation only, per non-negotiable 1: used here to place the
    synthetic culprit somewhere the field actually has mass, never fed
    into scoring."""
    prob = field_ds["probability"]
    flat_idx = int(np.argmax(prob.values))
    ti, yi, xi = np.unravel_index(flat_idx, prob.shape)
    lat = float(field_ds["lat"].values[yi])
    lon = float(field_ds["lon"].values[xi])
    time = pd.Timestamp(field_ds["time"].values[ti]).to_pydatetime()
    return lat, lon, time


def field_time_bounds(field_ds: xr.Dataset) -> tuple[datetime.datetime, datetime.datetime]:
    t_min = pd.Timestamp(field_ds["time"].values.min()).to_pydatetime()
    t_max = pd.Timestamp(field_ds["time"].values.max()).to_pydatetime()
    return t_min, t_max


def _interp_path(waypoints: list[Waypoint], ts: datetime.datetime) -> tuple[float, float]:
    if ts <= waypoints[0][2]:
        return waypoints[0][0], waypoints[0][1]
    if ts >= waypoints[-1][2]:
        return waypoints[-1][0], waypoints[-1][1]
    for (lat0, lon0, t0), (lat1, lon1, t1) in zip(waypoints, waypoints[1:]):
        if t0 <= ts <= t1:
            total = (t1 - t0).total_seconds()
            frac = 0.0 if total == 0 else (ts - t0).total_seconds() / total
            return great_circle_interpolate(lat0, lon0, lat1, lon1, frac)
    return waypoints[-1][0], waypoints[-1][1]


def build_track(
    mmsi: str,
    vessel_type: str,
    waypoints: list[Waypoint],
    ping_interval_min: float,
    rng: np.random.Generator,
    dark_gap_min_minutes: float,
    max_speed_kn: float,
    drop_between: tuple[datetime.datetime, datetime.datetime] | None = None,
) -> AISTrack:
    """Builds an AISTrack by sampling pings along a piecewise
    great-circle path through waypoints, at jittered ping_interval_min
    intervals (natural dropout rates should come from real
    MarineCadastre statistics, PLAN.md section 4A; jitter is a
    placeholder for that until they're available). Optionally drops
    pings inside drop_between to create a dark gap. Gaps are then
    detected the same way a real reconstruction would (ais/darkgaps.py),
    not hand-authored, so this exercises the real detection path rather
    than asserting its own answer."""
    t0, t_last = waypoints[0][2], waypoints[-1][2]
    timestamps = [t0]
    t = t0
    while t < t_last:
        t = t + datetime.timedelta(minutes=ping_interval_min * rng.uniform(0.8, 1.2))
        timestamps.append(min(t, t_last))
    if timestamps[-1] != t_last:
        timestamps.append(t_last)

    if drop_between is not None:
        drop_start, drop_end = drop_between
        timestamps = [ts for ts in timestamps if not (drop_start < ts < drop_end)]

    positions = [_interp_path(waypoints, ts) for ts in timestamps]

    points: list[AISPoint] = []
    for i, (ts, (lat, lon)) in enumerate(zip(timestamps, positions)):
        if i == 0:
            cog = bearing_deg(lat, lon, *positions[1]) if len(positions) > 1 else 0.0
            sog = 0.0
        else:
            prev_lat, prev_lon = positions[i - 1]
            prev_ts = timestamps[i - 1]
            cog = bearing_deg(prev_lat, prev_lon, lat, lon)
            dt_h = (ts - prev_ts).total_seconds() / 3600.0
            dist_km = haversine_km(prev_lat, prev_lon, lat, lon)
            sog = (dist_km / dt_h / 1.852) if dt_h > 0 else 0.0
        points.append(AISPoint(ts=ts, lat=lat, lon=lon, sog=sog, cog=cog))

    dark_gaps = find_dark_gaps(points, dark_gap_min_minutes, max_speed_kn)
    return AISTrack(mmsi=mmsi, vessel_type=vessel_type, points=points, dark_gaps=dark_gaps)


def generate_demo_scenario(field_ds: xr.Dataset, ais_config: dict, seed: int) -> list[AISTrack]:
    """Builds the culprit plus three hard negatives from PLAN.md section
    9, positioned relative to the origin field's peak so the scoring
    engine (P8) has something real to separate them on:

    - culprit: crosses the field's peak at the peak time, slows down,
      goes dark centred on that passage, resumes on a different course.
    - wrong_time: crosses the same location, well outside the field's
      own time window.
    - dark_far: has a dark gap of the same size as the culprit's, but
      far from the field's spatial support.
    - constant_speed_close: spatially close throughout the field's time
      window, but at constant transit speed with no dark gap.
    """
    rng = np.random.default_rng(seed)
    dark_gap_min = ais_config["dark_gap_min_minutes"]
    max_speed_kn = ais_config["max_plausible_speed_kn"]

    peak_lat, peak_lon, peak_time = field_peak(field_ds)
    t_min, t_max = field_time_bounds(field_ds)

    lat_span = float(field_ds["lat"].values.max() - field_ds["lat"].values.min())
    lon_span = float(field_ds["lon"].values.max() - field_ds["lon"].values.min())
    offset = max(lat_span, lon_span) * 1.5 + 0.05
    leg = datetime.timedelta(hours=1)

    tracks = []

    culprit_waypoints: list[Waypoint] = [
        (peak_lat - offset, peak_lon - offset, peak_time - leg),
        (peak_lat, peak_lon, peak_time),
        (peak_lat + offset * 0.6, peak_lon - offset * 0.8, peak_time + leg),
    ]
    culprit_drop = (peak_time - datetime.timedelta(minutes=25), peak_time + datetime.timedelta(minutes=25))
    tracks.append(
        build_track(
            "419000001", "tanker", culprit_waypoints, ping_interval_min=8, rng=rng,
            dark_gap_min_minutes=dark_gap_min, max_speed_kn=max_speed_kn, drop_between=culprit_drop,
        )
    )

    wrong_time = t_min - datetime.timedelta(hours=12)
    wrong_time_waypoints: list[Waypoint] = [
        (peak_lat - offset, peak_lon - offset, wrong_time - leg),
        (peak_lat, peak_lon, wrong_time),
        (peak_lat + offset, peak_lon + offset, wrong_time + leg),
    ]
    tracks.append(
        build_track(
            "419000002", "cargo", wrong_time_waypoints, ping_interval_min=10, rng=rng,
            dark_gap_min_minutes=dark_gap_min, max_speed_kn=max_speed_kn,
        )
    )

    far_lat, far_lon = peak_lat + offset * 8, peak_lon + offset * 8
    far_waypoints: list[Waypoint] = [
        (far_lat - offset, far_lon - offset, peak_time - leg),
        (far_lat, far_lon, peak_time),
        (far_lat + offset, far_lon + offset, peak_time + leg),
    ]
    far_drop = (peak_time - datetime.timedelta(minutes=25), peak_time + datetime.timedelta(minutes=25))
    tracks.append(
        build_track(
            "419000003", "cargo", far_waypoints, ping_interval_min=8, rng=rng,
            dark_gap_min_minutes=dark_gap_min, max_speed_kn=max_speed_kn, drop_between=far_drop,
        )
    )

    constant_speed_waypoints: list[Waypoint] = [
        (peak_lat - offset, peak_lon + offset, peak_time - leg),
        (peak_lat, peak_lon + offset * 0.2, peak_time),
        (peak_lat + offset, peak_lon + offset * 0.4, peak_time + leg),
    ]
    tracks.append(
        build_track(
            "419000004", "fishing", constant_speed_waypoints, ping_interval_min=8, rng=rng,
            dark_gap_min_minutes=dark_gap_min, max_speed_kn=max_speed_kn,
        )
    )

    return tracks
