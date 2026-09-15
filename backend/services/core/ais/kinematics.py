"""Ship motion that a ship could actually perform. See PLAN.md section 10.

The synthetic scenario used to place waypoints and interpolate straight
between them, which produces tracks no vessel can sail. Two things were
wrong with it, and both fed directly into factors that are supposed to
measure behaviour.

Course changed instantaneously at a waypoint. The demo's hard negative
turned 95 degrees across thirteen minutes with 84 of them inside a
single seven minute ping interval, and its reported course went
0, 0, 0, +11, +84, 0, 0, 0. A real manoeuvre does not look remotely like
that: a vessel under helm holds a sustained rate of turn for the whole
manoeuvre, so the same 95 degrees arrives as a plateau spread over many
pings. F5 scores course anomaly, so it was scoring the shape of a corner
in the fixture rather than the shape of a manoeuvre.

Speed changed instantaneously too. The culprit went from 10.5 knots to
1.0 knots between consecutive pings. A loaded merchant vessel reducing
from a transit speed to a crawl takes ten to fifteen minutes and over a
mile of water. F4 scores sustained speed deviation, so it inherited the
same problem.

This module replaces the interpolation with a small kinematic
integration. The vessel has a heading and a speed; it steers towards its
next waypoint at a bounded rate of turn and changes speed at a bounded
rate. Position is integrated at a fine timestep and the AIS pings are
then sampled from that continuous track, which is the order the real
world does it in: the vessel moves, and the transponder reports what it
finds.

The numbers below are ordinary ship-handling figures, not tuned to make
anything score a particular way. They are in one place so they can be
argued with.
"""

from __future__ import annotations

import datetime
import math

import numpy as np

KM_PER_DEG = 111.0
KM_PER_NM = 1.852

# Rate of turn under helm, degrees per second. A loaded merchant vessel
# manages roughly 0.2 to 0.5; the smaller end is the honest default for
# a laden tanker, and a fishing vessel is far more agile.
DEFAULT_MAX_ROT_DEG_S = 0.25
ROT_BY_TYPE: dict[str, float] = {
    "tanker": 0.20,
    "cargo": 0.25,
    "passenger": 0.40,
    "tug": 0.80,
    "fishing": 0.60,
}

# Steering wander, the small continuous hunting of a heading under
# autopilot or helm in a seaway, and the matching surge in speed. Each is
# an Ornstein-Uhlenbeck process: (standard deviation, correlation time in
# minutes). Wander perturbs the course the vessel is steering for, and the
# rate of turn bound still applies on top, so it bends a track into gentle
# curves rather than putting kinks in it. Small vessels hunt more.
WANDER_BY_TYPE: dict[str, dict[str, float]] = {
    "tanker": {"heading_sd_deg": 1.2, "heading_tau_min": 12.0, "speed_sd_kn": 0.15, "speed_tau_min": 25.0},
    "cargo": {"heading_sd_deg": 1.5, "heading_tau_min": 10.0, "speed_sd_kn": 0.20, "speed_tau_min": 20.0},
    "passenger": {"heading_sd_deg": 1.2, "heading_tau_min": 10.0, "speed_sd_kn": 0.25, "speed_tau_min": 15.0},
    "tug": {"heading_sd_deg": 3.0, "heading_tau_min": 6.0, "speed_sd_kn": 0.30, "speed_tau_min": 10.0},
    "fishing": {"heading_sd_deg": 5.0, "heading_tau_min": 5.0, "speed_sd_kn": 0.35, "speed_tau_min": 8.0},
}

# Speed change, knots per minute. Deceleration is faster than
# acceleration for a displacement hull: the water stops you far more
# willingly than the engine drives you.
DEFAULT_ACCEL_KN_MIN = 0.35
DEFAULT_DECEL_KN_MIN = 0.9

# Integration step. Fine enough that a 0.6 deg/s turn resolves smoothly,
# coarse enough that a three day track is cheap.
STEP_SECONDS = 20.0

# How close counts as arriving at a waypoint, in km. A vessel steering
# for a mark does not pass through it exactly, and insisting it does
# produces a hunting oscillation as the bearing swings wildly at close
# range.
ARRIVAL_RADIUS_KM = 0.35


def turn_radius_km(speed_kn: float, rot_deg_s: float) -> float:
    """Radius of the turning circle at this speed and rate of turn.

    A merchant vessel's turning circle is several ship lengths across:
    at 11 knots and 0.25 deg/s it is about 1.3 km. That is the scale on
    which a course change actually happens, and it is why a vessel puts
    the wheel over well before the mark rather than at it.
    """
    if rot_deg_s <= 0:
        return 0.0
    speed_ms = speed_kn * KM_PER_NM * 1000.0 / 3600.0
    omega = math.radians(rot_deg_s)
    return (speed_ms / omega) / 1000.0


def wheel_over_km(speed_kn: float, rot_deg_s: float, course_change_deg: float) -> float:
    """Distance before the mark at which the wheel goes over.

    Standard route-following geometry: to leave one leg and arrive on
    the next tangentially, the turn must start `R tan(theta/2)` short of
    the corner. Steering at the mark and turning afterwards instead puts
    the vessel through the corner and then swinging wide, which is both
    unrealistic and the wrong shape for a track.
    """
    change = min(abs(course_change_deg), 179.0)
    if change < 1.0:
        return 0.0
    return turn_radius_km(speed_kn, rot_deg_s) * math.tan(math.radians(change / 2.0))


def _km_per_deg_lon(lat: float) -> float:
    return KM_PER_DEG * math.cos(math.radians(lat)) or 1e-6


def bearing_to(lat0: float, lon0: float, lat1: float, lon1: float) -> float:
    """Initial bearing in degrees, 0 to 360, clockwise from north.

    Plane geometry with a latitude correction rather than a great
    circle: legs here are tens of kilometres, where the difference is
    far below AIS reporting precision, and it keeps the integration
    stable near the waypoint.
    """
    dy = lat1 - lat0
    dx = (lon1 - lon0) * math.cos(math.radians((lat0 + lat1) / 2))
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def distance_km(lat0: float, lon0: float, lat1: float, lon1: float) -> float:
    dy = (lat1 - lat0) * KM_PER_DEG
    dx = (lon1 - lon0) * _km_per_deg_lon((lat0 + lat1) / 2)
    return float(math.hypot(dx, dy))


def signed_turn(from_deg: float, to_deg: float) -> float:
    """Shortest signed turn between two headings, -180 to +180."""
    return (to_deg - from_deg + 180.0) % 360.0 - 180.0


def max_rot_for(vessel_type: str) -> float:
    return ROT_BY_TYPE.get(vessel_type, DEFAULT_MAX_ROT_DEG_S)


def sail(
    waypoints: list[tuple[float, float, datetime.datetime]],
    vessel_type: str = "cargo",
    max_rot_deg_s: float | None = None,
    accel_kn_min: float = DEFAULT_ACCEL_KN_MIN,
    decel_kn_min: float = DEFAULT_DECEL_KN_MIN,
    step_seconds: float = STEP_SECONDS,
    rng: np.random.Generator | None = None,
    wander: dict[str, float] | None = None,
) -> list[tuple[datetime.datetime, float, float, float, float]]:
    """Integrates a vessel through its waypoints under bounded turn and
    speed rates.

    Returns (time, lat, lon, cog, sog) at every integration step. The
    caller samples AIS pings from this, rather than the track being
    built out of the pings.

    Waypoint times are the vessel's intent, not a guarantee. The vessel
    aims to make each mark on schedule and works out the speed that
    requires, but it cannot change speed or heading faster than the
    bounds allow, so it arrives when the physics lets it. That is the
    right way round: a schedule that the hull cannot keep is the
    schedule's problem, and forcing the track to honour it is exactly
    how the instantaneous turns got in.

    With `rng`, the vessel also wanders: the course it steers and the
    speed it holds each carry an Ornstein-Uhlenbeck perturbation from
    WANDER_BY_TYPE (or `wander`). Without `rng` the integration is the
    exact deterministic one, which is what the kinematics tests measure.
    """
    if len(waypoints) < 2:
        raise ValueError("a track needs at least two waypoints")

    rot = max_rot_for(vessel_type) if max_rot_deg_s is None else max_rot_deg_s

    lat, lon, t = waypoints[0]
    heading = bearing_to(lat, lon, waypoints[1][0], waypoints[1][1])

    # Opening speed is whatever the first leg asks for, so the track does
    # not begin with an unphysical acceleration from rest.
    first_leg_km = distance_km(lat, lon, waypoints[1][0], waypoints[1][1])
    first_leg_h = max((waypoints[1][2] - t).total_seconds() / 3600.0, 1e-6)
    speed = float(np.clip(first_leg_km / first_leg_h / KM_PER_NM, 0.0, 25.0))

    out: list[tuple[datetime.datetime, float, float, float, float]] = [
        (t, lat, lon, heading, speed)
    ]

    target_index = 1
    t_end = waypoints[-1][2]
    step = datetime.timedelta(seconds=step_seconds)

    w = None
    if rng is not None:
        w = {**WANDER_BY_TYPE.get(vessel_type, WANDER_BY_TYPE["cargo"]), **(wander or {})}
    heading_offset = 0.0
    speed_offset = 0.0

    while t < t_end and target_index < len(waypoints):
        tgt_lat, tgt_lon, tgt_time = waypoints[target_index]

        to_go_km = distance_km(lat, lon, tgt_lat, tgt_lon)

        # Wheel-over: start the turn early enough that the turning circle
        # delivers the vessel onto the next leg, rather than sailing to
        # the mark and turning once past it.
        wheel_over = 0.0
        if target_index + 1 < len(waypoints):
            nxt = waypoints[target_index + 1]
            leg_in = bearing_to(lat, lon, tgt_lat, tgt_lon)
            leg_out = bearing_to(tgt_lat, tgt_lon, nxt[0], nxt[1])
            wheel_over = wheel_over_km(speed, rot, signed_turn(leg_in, leg_out))

        # Advance the mark once reached or wheeled over, or once its time
        # has passed: a vessel that has been held up does not sail back
        # to a waypoint it is already late for.
        if to_go_km < max(ARRIVAL_RADIUS_KM, wheel_over) or t >= tgt_time:
            target_index += 1
            continue

        if w is not None:
            # Exact OU update over one step, so the wander statistics do
            # not depend on the integration step.
            a_h = math.exp(-step_seconds / (60.0 * w["heading_tau_min"]))
            heading_offset = a_h * heading_offset + w["heading_sd_deg"] * math.sqrt(1 - a_h * a_h) * float(rng.normal())
            a_s = math.exp(-step_seconds / (60.0 * w["speed_tau_min"]))
            speed_offset = a_s * speed_offset + w["speed_sd_kn"] * math.sqrt(1 - a_s * a_s) * float(rng.normal())

        # Steer towards the mark, bounded by the rate of turn.
        desired_heading = (bearing_to(lat, lon, tgt_lat, tgt_lon) + heading_offset) % 360.0
        turn = signed_turn(heading, desired_heading)
        max_turn = rot * step_seconds
        heading = (heading + float(np.clip(turn, -max_turn, max_turn))) % 360.0

        # Speed needed to make the mark on time, bounded by how fast the
        # hull can change speed.
        remaining_h = max((tgt_time - t).total_seconds() / 3600.0, 1e-6)
        desired_speed = float(np.clip(to_go_km / remaining_h / KM_PER_NM + speed_offset, 0.0, 25.0))
        delta = desired_speed - speed
        max_delta = (accel_kn_min if delta > 0 else decel_kn_min) * (step_seconds / 60.0)
        speed += float(np.clip(delta, -max_delta, max_delta))
        speed = max(speed, 0.0)

        # Integrate one step along the current heading.
        run_km = speed * KM_PER_NM * (step_seconds / 3600.0)
        lat += (run_km * math.cos(math.radians(heading))) / KM_PER_DEG
        lon += (run_km * math.sin(math.radians(heading))) / _km_per_deg_lon(lat)
        t = t + step

        out.append((t, lat, lon, heading, speed))

    return out


def sample_at_times(
    path: list[tuple[datetime.datetime, float, float, float, float]],
    times: list[datetime.datetime],
) -> list[tuple[float, float, float, float]]:
    """Reads (lat, lon, cog, sog) off an integrated path at given times.

    Nearest step rather than interpolated. The steps are 20 seconds
    apart, well inside AIS position precision, and interpolating between
    them would smooth the very turn dynamics this module exists to
    preserve.
    """
    if not path:
        return []
    stamps = np.array([p[0].timestamp() for p in path])
    out = []
    for when in times:
        i = int(np.abs(stamps - when.timestamp()).argmin())
        _, lat, lon, cog, sog = path[i]
        out.append((lat, lon, cog, sog))
    return out


def sustained_rot_profile(cogs: list[float], seconds: list[float]) -> list[float]:
    """Rate of turn between consecutive reports, degrees per second.

    Used by the tests. A real manoeuvre shows a plateau here; an
    interpolated corner shows a single spike surrounded by zeros, and
    telling those apart is the whole point of this module.
    """
    out = []
    for i in range(1, len(cogs)):
        dt = seconds[i] - seconds[i - 1]
        if dt <= 0:
            continue
        out.append(abs(signed_turn(cogs[i - 1], cogs[i])) / dt)
    return out
