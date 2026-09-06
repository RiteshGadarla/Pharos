"""Synthetic AIS traffic generator for the demo scenario. See PLAN.md
section 10.

The problem statement explicitly permits this: "Real AIS if available
may be used else synthetic data can be prepared for the region of oil
spill to demonstrate the functioning of the algorithm." The sentence is
recorded verbatim at the top of config/demo.yaml. Permission is not an
excuse to be sloppy.

Lane geometry, vessel type mix, speed distributions and dropout rates
should be fitted from real MarineCadastre statistics, the format
authority the PS itself names; that data is not available yet (PLAN.md
section 4A), so this uses documented placeholder values instead. Only
the scenario shape, one culprit and four hard negatives positioned
relative to wherever the origin field's mass actually is, reflects the
plan's design. Swap the distributions for real fitted ones without
touching the scenario logic or the scoring engine that consumes it.
"""

from __future__ import annotations

import datetime
import math

import numpy as np
import pandas as pd
import xarray as xr

from shapely.geometry import Point, shape

from services.core.ais.darkgaps import find_dark_gaps
from services.core.ais.kinematics import sail, sample_at_times
from services.core.ais.tracks import bearing_deg, great_circle_interpolate, haversine_km, position_at
from services.core.schemas import AISPoint, AISTrack, ShipTarget

Waypoint = tuple[float, float, datetime.datetime]  # lat, lon, time

KM_PER_DEG = 111.0
KM_PER_NM = 1.852
# Plausible loaded merchant transit speed, used to size the synthetic
# tracks' leg durations from their geometry.
TRANSIT_SPEED_KN = 11.0

# How far either side of the origin the culprit's slow segment runs, in
# degrees. About 900 m, covered over 45 minutes, which is roughly 0.7
# knots: the steady crawl of an operational discharge rather than a
# transit. Small deliberately, so the vessel is still over the origin
# when the satellite passes.
SLOW_LEG_OFFSET_DEG = 0.008


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


def field_peak_at(field_ds: xr.Dataset, at_time: datetime.datetime) -> tuple[float, float, datetime.datetime]:
    """Returns (lat, lon, time) of the highest-mass cell WITHIN the time
    slice nearest `at_time`.

    `field_peak` takes the argmax over the whole space-time volume, and
    that can only ever land near the acquisition instant: the field is
    most concentrated there because the ensemble members have not yet
    diverged, so the peak cell density falls monotonically as the
    hindcast runs backwards. Building the demo scenario around the
    global argmax therefore placed the culprit at the slick's own
    position at the moment of observation, every time, whatever the
    backward horizon was. The 48 hour reconstruction was computed and
    drawn but never actually used to find anyone: the ranking came down
    to which vessel was beside the slick when the satellite passed,
    which is the proximity reasoning this system exists to replace.

    Slicing first and taking the argmax second is what lets the scenario
    place an origin genuinely in the past.

    Orientation only, per non-negotiable 1: used to place synthetic
    vessels somewhere the field actually has mass, never fed into
    scoring.
    """
    slice_ds = field_ds["probability"].sel(time=np.datetime64(at_time), method="nearest")
    flat_idx = int(np.argmax(slice_ds.values))
    yi, xi = np.unravel_index(flat_idx, slice_ds.shape)
    lat = float(field_ds["lat"].values[yi])
    lon = float(field_ds["lon"].values[xi])
    time = pd.Timestamp(slice_ds["time"].values).to_pydatetime()
    return lat, lon, time


def field_support_deg(field_ds: xr.Dataset, at_time: datetime.datetime) -> float:
    """Characteristic spatial spread of the field at one timestep, in
    degrees: the mass-weighted RMS distance of that slice from its own
    centroid.

    This is what "spatially close" has to be measured against. The grid's
    extent is not a substitute: the grid is sized to hold every particle
    from every member across the whole backward horizon, while the mass
    at any one timestep sits in a small part of it. Placing the close
    hard negative at a fraction of the grid span put it several spreads
    off the mass, where the field is effectively zero, so it was
    eliminated for no spatial support instead of being scored.
    """
    prob = field_ds["probability"]
    ti = int(np.abs(field_ds["time"].values - np.datetime64(at_time)).argmin())
    slice_ = prob.values[ti]
    mass = slice_.sum()
    if mass <= 0:
        return 0.0

    weights = slice_ / mass
    lat = field_ds["lat"].values
    lon = field_ds["lon"].values
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    centre_lat = float((weights * lat_grid).sum())
    centre_lon = float((weights * lon_grid).sum())
    variance = float((weights * ((lat_grid - centre_lat) ** 2 + (lon_grid - centre_lon) ** 2)).sum())
    return float(np.sqrt(variance))


def _envelope_reach_deg(gap_minutes: float, max_speed_kn: float, lat: float) -> float:
    """How far, in degrees of longitude at this latitude, a vessel could
    have travelled during a gap of this length at its plausible maximum
    speed. This is the radius of the reach disks ais/darkgaps.py
    intersects to build a dead-reckoned envelope, so it is what a hard
    negative has to clear to keep a radar target out of its own
    envelope."""
    reach_km = max_speed_kn * KM_PER_NM * (gap_minutes / 60.0)
    km_per_deg_lon = KM_PER_DEG * np.cos(np.radians(lat)) or 1e-6
    return float(reach_km / km_per_deg_lon)


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
    # The vessel is sailed first and the transponder samples it second,
    # which is the order the real world does it in. Building the track
    # out of the pings instead is what produced 84 degree turns inside a
    # single ping interval and 10 knot speed drops between consecutive
    # reports: the interpolation honoured the waypoint schedule exactly,
    # and no hull can.
    path = sail(waypoints, vessel_type=vessel_type)
    t0, t_last = path[0][0], path[-1][0]

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

    # Course and speed come from the vessel's own state at that instant,
    # not from differencing consecutive positions. Differencing reports
    # the chord between two pings, which understates speed through a
    # turn and reports a course the vessel never steered.
    sampled = sample_at_times(path, timestamps)

    points: list[AISPoint] = []
    for ts, (lat, lon, cog, sog) in zip(timestamps, sampled):
        points.append(AISPoint(ts=ts, lat=lat, lon=lon, sog=round(sog, 2), cog=round(cog, 1), heading=round(cog, 1)))

    dark_gaps = find_dark_gaps(points, dark_gap_min_minutes, max_speed_kn)
    return AISTrack(mmsi=mmsi, vessel_type=vessel_type, points=points, dark_gaps=dark_gaps)


def extend_to(waypoints: list[Waypoint], until: datetime.datetime) -> list[Waypoint]:
    """Continues a track past its last waypoint on the same bearing at
    transit speed, up to `until`.

    Needed once the origin sits hours before acquisition. The scenario's
    legs are built around the origin time, so moving the origin back
    moves every vessel back with it, and without this the whole fleet
    would vanish from the map well before the satellite pass: the
    scrubber would show an empty sea at the one instant the SAR image
    actually documents.

    It is also the physically honest continuation. A vessel that
    discharged fourteen hours ago did not stop there, it carried on, and
    where it carried on to is exactly what a dead-reckoned search would
    ask about. The distance travelled is elapsed time at transit speed,
    so the extension cannot fire the implied_speed integrity flag it
    would trip if it teleported.
    """
    if not waypoints:
        return waypoints
    last_lat, last_lon, last_t = waypoints[-1]
    elapsed_h = (until - last_t).total_seconds() / 3600.0
    if elapsed_h <= 0:
        return waypoints

    # Bearing of the final leg, as a unit vector in degrees.
    if len(waypoints) >= 2:
        prev_lat, prev_lon, _ = waypoints[-2]
        dy, dx = last_lat - prev_lat, last_lon - prev_lon
        norm = float(np.hypot(dy, dx))
        if norm == 0:
            dy, dx, norm = 1.0, 0.0, 1.0
        dy, dx = dy / norm, dx / norm
    else:
        dy, dx = 1.0, 0.0

    dist_deg = elapsed_h * TRANSIT_SPEED_KN * KM_PER_NM / KM_PER_DEG
    return [*waypoints, (last_lat + dy * dist_deg, last_lon + dx * dist_deg, until)]


def generate_demo_scenario(
    field_ds: xr.Dataset,
    ais_config: dict,
    seed: int,
    include_culprit_dark_gap: bool = True,
    origin_lag_hours: float | None = None,
    acquired_at: datetime.datetime | None = None,
) -> list[AISTrack]:
    """Builds the culprit plus four hard negatives from PLAN.md section
    10, positioned relative to the origin field's peak so the scoring
    engine (P8) has something real to separate them on:

    - culprit: crosses the field's peak at the peak time, slows down,
      goes dark centred on that passage, resumes on a different course.
    - wrong_time: crosses the same location, well outside the field's
      own time window.
    - dark_far: has a dark gap of the same size as the culprit's, but
      far from the field's spatial support.
    - constant_speed_close: spatially close throughout the field's time
      window, but at constant transit speed with no dark gap.
    - dark_no_radar: goes dark over the field, like the culprit, but no
      unmatched radar target sits inside its envelope, so F8 does not
      fire for it. This negative exists specifically to prove F8
      discriminates rather than merely rewarding darkness: without it,
      a scoring engine that simply added points for going dark would
      look identical to one that requires an independent observation.

    include_culprit_dark_gap=False keeps the culprit's slow-down but
    skips dropping its pings, so it stays fully visible throughout. This
    is the validation harness's "dark gap presence" axis (PLAN.md
    section 17.1): with no gap to detect, F2 (dark_overlap) can't
    contribute anything, so this checks whether the other factors alone
    still separate the culprit from the hard negatives.

    origin_lag_hours puts the discharge that many hours BEFORE
    acquisition, which is what makes the scenario exercise the backward
    reconstruction at all. Without it the origin comes from the field's
    global argmax, which is always within a timestep of acquisition (see
    field_peak_at), so the culprit sits on the slick's observed position
    and the ranking degenerates into proximity to the current oil.
    The lag should come from the slick's own age band, so the scenario
    is consistent with what the characterisation measured rather than
    with a number chosen to make the demo work.

    Left as None the old global-argmax behaviour applies, which is what
    the validation harness's synthetic incidents and the contract tests
    still use.
    """
    rng = np.random.default_rng(seed)
    dark_gap_min = ais_config["dark_gap_min_minutes"]
    max_speed_kn = ais_config["max_plausible_speed_kn"]

    if origin_lag_hours is not None:
        if acquired_at is None:
            raise ValueError("origin_lag_hours needs acquired_at to know what the lag is measured from")
        origin_time = acquired_at - datetime.timedelta(hours=float(origin_lag_hours))
        peak_lat, peak_lon, peak_time = field_peak_at(field_ds, origin_time)
    else:
        peak_lat, peak_lon, peak_time = field_peak(field_ds)
    t_min, t_max = field_time_bounds(field_ds)

    lat_span = float(field_ds["lat"].values.max() - field_ds["lat"].values.min())
    lon_span = float(field_ds["lon"].values.max() - field_ds["lon"].values.min())
    max_span = max(lat_span, lon_span)

    # How far out the tracks start, and how far apart the hard negatives
    # sit. Both scale with the field, since a field twice as wide needs
    # vessels that run twice as far to cross it, with a floor so a narrow
    # field still produces tracks long enough to see.
    offset = max(0.25, max_span * 0.9)
    # The "spatially close" hard negative passes this far from the peak.
    # Measured in the field's own spread, so it stays inside the mass at
    # any horizon, and far enough out to be a distinct track on screen
    # rather than sitting on top of the culprit.
    close_offset = field_support_deg(field_ds, peak_time) * 1.5
    far_offset = max(1.0, max_span * 3.0)

    # Leg duration is derived from the geometry and a plausible transit
    # speed, not fixed. It used to be one hour regardless, while the
    # geometry scaled off the field's grid span, so widening the field
    # silently accelerated every synthetic vessel: on a 48 hour backward
    # horizon they exceeded 35 knots, which is not traffic any scoring
    # engine should be asked to treat as ordinary.
    leg_km = float(np.hypot(offset, offset)) * KM_PER_DEG
    leg = datetime.timedelta(hours=leg_km / (TRANSIT_SPEED_KN * KM_PER_NM))

    tracks = []

    # An operational discharge is a straight, slow run, not a dogleg.
    #
    # The culprit used to be given a tight two-legged turn over the
    # origin, and the straight-line interpolation happily drew it. Under
    # real ship handling it is impossible: a laden tanker at 10.5 knots
    # turning at 0.20 deg/s has a turning circle of about 1.55 km, which
    # is wider than the entire 900 m slow leg it was asked to perform.
    # Sailed properly, the vessel wheels over before it ever reaches the
    # origin, misses it entirely, and scores a field integral of zero.
    #
    # The realistic behaviour is also the better scenario. A vessel
    # discharging holds its course and slows: that is how a discharge
    # streak comes to be elongated ALONG the vessel's track, which is the
    # geometry F3 (axis alignment) exists to detect. So the approach, the
    # discharge and the departure are one straight line, and the only
    # course change is a gentle one well afterwards, which is what F5 is
    # meant to find.
    approach_bearing_deg = 60.0
    brg = math.radians(approach_bearing_deg)
    lat_step = math.cos(brg)
    lon_step = math.sin(brg) / max(math.cos(math.radians(peak_lat)), 1e-6)

    def transit(
        through_lat: float, through_lon: float, bearing_deg: float,
        half_deg: float, t_centre: datetime.datetime, half_leg: datetime.timedelta,
    ) -> list[Waypoint]:
        """A straight transit passing through a point on a bearing.

        Two waypoints, so there is no turn in it at all. The hard
        negatives used to be V shapes: in to the origin on one bearing
        and back out on the reciprocal, which is a vessel sailing to a
        point and turning round. Traffic does not do that. It follows a
        lane, which is straight, and passes by.
        """
        b = math.radians(bearing_deg)
        dlat = math.cos(b) * half_deg
        dlon = math.sin(b) * half_deg / max(math.cos(math.radians(through_lat)), 1e-6)
        return [
            (through_lat - dlat, through_lon - dlon, t_centre - half_leg),
            (through_lat + dlat, through_lon + dlon, t_centre + half_leg),
        ]

    def along(distance_deg: float) -> tuple[float, float]:
        """A point `distance_deg` along the approach bearing from the
        origin. Negative is before it."""
        return (peak_lat + lat_step * distance_deg, peak_lon + lon_step * distance_deg)

    # Distances along the track, in degrees. The slow run is sized so the
    # vessel is genuinely crawling for the better part of an hour: 0.024
    # degrees is about 2.7 km, covered in 40 minutes, which is 2.2 knots.
    SLOW_HALF_DEG = 0.012
    DECEL_ZONE_DEG = 0.030
    slow_half = datetime.timedelta(minutes=20)
    decel_span = datetime.timedelta(minutes=40)

    culprit_waypoints: list[Waypoint] = [
        (*along(-offset), peak_time - leg - decel_span),
        (*along(-DECEL_ZONE_DEG), peak_time - decel_span),
        (*along(-SLOW_HALF_DEG), peak_time - slow_half),
        (*along(SLOW_HALF_DEG), peak_time + slow_half),
        (*along(DECEL_ZONE_DEG), peak_time + decel_span),
        (*along(offset * 0.6), peak_time + leg + decel_span),
    ]

    # The course change, hours after the discharge and gentle enough for
    # a laden hull: 30 degrees, made in open water with room for the
    # turning circle. This is what F5 has to find, and it has to be a
    # manoeuvre rather than a corner or F5 is scoring the fixture.
    turn_bearing = math.radians(approach_bearing_deg + 30.0)
    turn_from = along(offset * 0.6)
    run_out = offset * 0.9
    culprit_waypoints.append((
        turn_from[0] + math.cos(turn_bearing) * run_out,
        turn_from[1] + math.sin(turn_bearing) * run_out / max(math.cos(math.radians(peak_lat)), 1e-6),
        peak_time + leg * 2 + decel_span,
    ))

    # Every vessel except wrong_time is carried through to the end of
    # the field's window, so the fleet is still on screen at the
    # acquisition instant. wrong_time is left alone: being outside the
    # window is the entire point of that negative, and extending it into
    # the window would delete the hard case it exists to pose.
    tail = t_max if origin_lag_hours is not None else None
    if tail is not None:
        culprit_waypoints = extend_to(culprit_waypoints, tail)

    culprit_drop = (
        (peak_time - datetime.timedelta(minutes=25), peak_time + datetime.timedelta(minutes=25))
        if include_culprit_dark_gap
        else None
    )
    tracks.append(
        build_track(
            "419000001", "tanker", culprit_waypoints, ping_interval_min=8, rng=rng,
            dark_gap_min_minutes=dark_gap_min, max_speed_kn=max_speed_kn, drop_between=culprit_drop,
        )
    )

    wrong_time = t_min - datetime.timedelta(hours=12)
    wrong_time_waypoints = transit(peak_lat, peak_lon, 45.0, offset, wrong_time, leg)
    tracks.append(
        build_track(
            "419000002", "cargo", wrong_time_waypoints, ping_interval_min=10, rng=rng,
            dark_gap_min_minutes=dark_gap_min, max_speed_kn=max_speed_kn,
        )
    )

    far_lat, far_lon = peak_lat + far_offset, peak_lon + far_offset
    far_waypoints = transit(far_lat, far_lon, 45.0, offset, peak_time, leg)
    if tail is not None:
        far_waypoints = extend_to(far_waypoints, tail)
    far_drop = (peak_time - datetime.timedelta(minutes=25), peak_time + datetime.timedelta(minutes=25))
    tracks.append(
        build_track(
            "419000003", "cargo", far_waypoints, ping_interval_min=8, rng=rng,
            dark_gap_min_minutes=dark_gap_min, max_speed_kn=max_speed_kn, drop_between=far_drop,
        )
    )

    # Passes through the field's mass at the peak time, like the culprit,
    # but at steady transit speed and without ever going dark. This is
    # the negative that stops "was near the origin" alone from convicting.
    # Straight past the origin at transit speed, offset laterally by
    # roughly one field spread. Same bearing family as the culprit, so
    # the only things separating them are speed and darkness, which is
    # what this negative exists to test.
    constant_speed_waypoints = transit(
        peak_lat, peak_lon + close_offset, 60.0, offset, peak_time, leg,
    )
    if tail is not None:
        constant_speed_waypoints = extend_to(constant_speed_waypoints, tail)
    tracks.append(
        build_track(
            "419000004", "fishing", constant_speed_waypoints, ping_interval_min=8, rng=rng,
            dark_gap_min_minutes=dark_gap_min, max_speed_kn=max_speed_kn,
        )
    )

    # Goes dark over the field, like the culprit, but its dead-reckoned
    # envelope does not contain the unmatched radar target, so F8 stays
    # at zero for it. This is the control that separates "went dark near
    # the origin" from "went dark near the origin and radar photographed
    # a hull there".
    #
    # It is separated in TIME, not in space, and that is forced by the
    # geometry rather than chosen for convenience. A dead-reckoned
    # envelope grows at the vessel's plausible maximum speed, so the
    # culprit's fifty minute gap reaches nearly fifty kilometres, wider
    # than the whole origin field. No vessel with a gap that long,
    # anywhere in the field, could exclude the target on distance alone.
    #
    # Time separates them cleanly instead, and for a real reason rather
    # than a convenient one: a radar target is a single observation at a
    # single instant, so it can only ever be evidence about a vessel
    # that was dark at that same instant (crosscheck/radar.py enforces
    # this). This vessel goes dark earlier in the window and is
    # transmitting again by the time the satellite passes, so the hull
    # in the image cannot be it. Its track still crosses the field's
    # mass, so it survives elimination and is scored on the other
    # factors, which is what makes it a hard negative rather than a
    # vessel that was simply never in the picture.
    short_gap_minutes = dark_gap_min * 1.4
    early_gap_centre = peak_time - leg * 0.5
    dark_no_radar_waypoints = transit(
        peak_lat, peak_lon - close_offset, 105.0, offset, peak_time, leg,
    )
    if tail is not None:
        dark_no_radar_waypoints = extend_to(dark_no_radar_waypoints, tail)
    half_gap = datetime.timedelta(minutes=short_gap_minutes / 2.0)
    dark_no_radar_drop = (early_gap_centre - half_gap, early_gap_centre + half_gap)
    tracks.append(
        build_track(
            "419000005", "cargo", dark_no_radar_waypoints, ping_interval_min=8, rng=rng,
            dark_gap_min_minutes=dark_gap_min, max_speed_kn=max_speed_kn,
            drop_between=dark_no_radar_drop,
        )
    )

    return tracks


def inject_ship_targets(
    tracks: list[AISTrack],
    field_ds: xr.Dataset,
    acquired_at: datetime.datetime,
    culprit_mmsi: str = "419000001",
) -> list[ShipTarget]:
    """Synthetic ShipTarget records for the demo scene. See PLAN.md
    section 11.

    The fixture scene's detector finds no ships (its synthetic sea has
    no hulls in it), so the radar cross check has nothing to work on
    unless the scenario provides it. This builds that layer the same way
    the AIS is built: one target per broadcasting vessel at its
    acquisition-time position, so the matcher has real work to do, plus
    exactly one unmatched target inside the culprit's dark envelope,
    which is the hull the radar saw and AIS did not report.

    Every other vessel's target is placed at that vessel's own
    interpolated position, so a broken matcher shows up as a fleet of
    false unmatched targets rather than passing silently.
    """
    targets: list[ShipTarget] = []
    for track in tracks:
        pos = position_at(track, acquired_at)
        if pos is None:
            continue
        lat, lon = pos
        targets.append(
            ShipTarget(
                target_id=f"SYNTH-ship-{len(targets):03d}",
                scene_id="DRISHTA-DEMO-0001",
                centroid=(lon, lat),
                pixel_area=int(40 + 20 * (track.vessel_type == "tanker")),
                mean_backscatter_db=-4.5,
            )
        )

    culprit = next((t for t in tracks if t.mmsi == culprit_mmsi), None)
    gap = next(
        (g for g in (culprit.dark_gaps if culprit else []) if g.start <= acquired_at <= g.end),
        None,
    )
    if gap is not None:
        # Placed where dead reckoning actually puts the vessel at the
        # acquisition instant: interpolated along the straight line from
        # where it went dark to where it came back, at the right
        # fraction of the way through the gap. That point is inside the
        # envelope by construction, and it is where the hull most
        # plausibly was, which is also where the origin field has its
        # mass. The envelope's centroid is neither: it is the centre of
        # a fifty kilometre lens of possibilities, and putting the
        # target there placed it in a cell holding almost none of the
        # field's probability, which made F8 numerically negligible for
        # a case it should have spoken loudly about.
        span = (gap.end - gap.start).total_seconds()
        frac = ((acquired_at - gap.start).total_seconds() / span) if span > 0 else 0.5
        lon = gap.entry_point[0] + frac * (gap.exit_point[0] - gap.entry_point[0])
        lat = gap.entry_point[1] + frac * (gap.exit_point[1] - gap.entry_point[1])
        point = Point(lon, lat)
        if not shape(gap.envelope).contains(point):
            point = shape(gap.envelope).representative_point()
        targets.append(
            ShipTarget(
                target_id="SYNTH-ship-unmatched",
                scene_id="DRISHTA-DEMO-0001",
                centroid=(float(point.x), float(point.y)),
                pixel_area=64,
                mean_backscatter_db=-3.8,
            )
        )
    return targets


DECOY_VESSEL_TYPES = ["cargo", "tanker", "fishing"]


def generate_decoy_vessels(field_ds: xr.Dataset, ais_config: dict, seed: int, n_vessels: int) -> list[AISTrack]:
    """Ordinary background traffic: no relationship to the origin field,
    normal transit speed, no dark gap. Used by the validation harness's
    "traffic density" axis (PLAN.md section 17.1) to check that the
    culprit still separates from the field once it isn't the only other
    vessel in the scene. Waypoints are random within a box a few times
    wider than the field itself, some passing near it and some not, the
    way real ambient shipping traffic would."""
    if n_vessels <= 0:
        return []

    rng = np.random.default_rng(seed)
    dark_gap_min = ais_config["dark_gap_min_minutes"]
    max_speed_kn = ais_config["max_plausible_speed_kn"]

    t_min, t_max = field_time_bounds(field_ds)
    lat_center = float(field_ds["lat"].values.mean())
    lon_center = float(field_ds["lon"].values.mean())
    lat_span = float(field_ds["lat"].values.max() - field_ds["lat"].values.min())
    lon_span = float(field_ds["lon"].values.max() - field_ds["lon"].values.min())
    box = max(lat_span, lon_span) * 6.0 + 0.1

    tracks = []
    for i in range(n_vessels):
        start_lat = lat_center + rng.uniform(-box, box)
        start_lon = lon_center + rng.uniform(-box, box)
        end_lat = lat_center + rng.uniform(-box, box)
        end_lon = lon_center + rng.uniform(-box, box)
        start_time = t_min - datetime.timedelta(hours=float(rng.uniform(0, 6)))
        end_time = t_max + datetime.timedelta(hours=float(rng.uniform(0, 6)))
        waypoints: list[Waypoint] = [(start_lat, start_lon, start_time), (end_lat, end_lon, end_time)]
        vessel_type = DECOY_VESSEL_TYPES[int(rng.integers(0, len(DECOY_VESSEL_TYPES)))]
        tracks.append(
            build_track(
                f"419000{100 + i:03d}", vessel_type, waypoints, ping_interval_min=10, rng=rng,
                dark_gap_min_minutes=dark_gap_min, max_speed_kn=max_speed_kn,
            )
        )
    return tracks
