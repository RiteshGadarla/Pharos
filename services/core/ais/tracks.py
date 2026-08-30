"""AIS track reconstruction. See PLAN.md section 9.

Interpolates a continuous position function between pings using
great-circle interpolation, and interpolates the vessel's own reported
SOG/COG the same way. No position is claimed during a dark gap: that
ambiguity is exactly what the gap's dead-reckoned envelope exists to
represent instead (ais/darkgaps.py).
"""

from __future__ import annotations

import datetime
import math

from services.core.schemas import AISTrack


def great_circle_interpolate(lat1: float, lon1: float, lat2: float, lon2: float, fraction: float) -> tuple[float, float]:
    """Spherical linear interpolation between two lat/lon points."""
    phi1, lam1 = math.radians(lat1), math.radians(lon1)
    phi2, lam2 = math.radians(lat2), math.radians(lon2)

    d = 2 * math.asin(
        math.sqrt(
            math.sin((phi2 - phi1) / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin((lam2 - lam1) / 2) ** 2
        )
    )
    if d == 0:
        return lat1, lon1

    a = math.sin((1 - fraction) * d) / math.sin(d)
    b = math.sin(fraction * d) / math.sin(d)
    x = a * math.cos(phi1) * math.cos(lam1) + b * math.cos(phi2) * math.cos(lam2)
    y = a * math.cos(phi1) * math.sin(lam1) + b * math.cos(phi2) * math.sin(lam2)
    z = a * math.sin(phi1) + b * math.sin(phi2)
    phi = math.atan2(z, math.sqrt(x**2 + y**2))
    lam = math.atan2(y, x)
    return math.degrees(phi), math.degrees(lam)


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    y = math.sin(dlam) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * earth_radius_km * math.asin(math.sqrt(a))


def _in_a_dark_gap(track: AISTrack, t: datetime.datetime) -> bool:
    return any(gap.start <= t <= gap.end for gap in track.dark_gaps)


def position_at(track: AISTrack, t: datetime.datetime) -> tuple[float, float] | None:
    """Interpolated (lat, lon) at time t. None if t falls outside the
    track's own ping range, or inside a dark gap (no position claim
    during a gap, per the module docstring)."""
    points = track.points
    if not points or t < points[0].ts or t > points[-1].ts:
        return None
    if _in_a_dark_gap(track, t):
        return None
    for p0, p1 in zip(points, points[1:]):
        if p0.ts <= t <= p1.ts:
            total = (p1.ts - p0.ts).total_seconds()
            frac = 0.0 if total == 0 else (t - p0.ts).total_seconds() / total
            return great_circle_interpolate(p0.lat, p0.lon, p1.lat, p1.lon, frac)
    return None


def course_and_speed_at(track: AISTrack, t: datetime.datetime) -> tuple[float, float] | None:
    """Interpolated (cog_deg, sog_kn) at time t, linear interpolation of
    the surrounding pings' own reported values. Course interpolates
    along the shorter arc so it wraps correctly through 0/360."""
    points = track.points
    if not points or t < points[0].ts or t > points[-1].ts:
        return None
    if _in_a_dark_gap(track, t):
        return None
    for p0, p1 in zip(points, points[1:]):
        if p0.ts <= t <= p1.ts:
            total = (p1.ts - p0.ts).total_seconds()
            frac = 0.0 if total == 0 else (t - p0.ts).total_seconds() / total
            sog = p0.sog + frac * (p1.sog - p0.sog)
            delta = ((p1.cog - p0.cog + 180) % 360) - 180
            cog = (p0.cog + frac * delta) % 360
            return cog, sog
    return None


def median_speed_kn(track: AISTrack) -> float:
    speeds = [p.sog for p in track.points]
    if not speeds:
        return 0.0
    speeds_sorted = sorted(speeds)
    mid = len(speeds_sorted) // 2
    if len(speeds_sorted) % 2 == 0:
        return (speeds_sorted[mid - 1] + speeds_sorted[mid]) / 2.0
    return speeds_sorted[mid]
