"""Dark gap detection and dead-reckoned reachable envelopes. See PLAN.md
section 9.

Dark periods raise suspicion, they never drop a vessel (non-negotiable
4): this module only detects and annotates gaps. Elimination and
scoring, which is where that suspicion actually gets used, live in
scoring/.
"""

from __future__ import annotations

import math

from shapely.affinity import scale, translate
from shapely.geometry import Point, mapping
from shapely.ops import unary_union

from services.core.schemas import AISPoint, DarkGap

KM_PER_DEG_LAT = 111.32


def _km_per_deg_lon(lat: float) -> float:
    return KM_PER_DEG_LAT * math.cos(math.radians(lat)) or 1e-6


def _circle_deg(center_lat: float, center_lon: float, radius_km: float, resolution: int = 32):
    """A near-circular polygon in degree space: a unit circle scaled
    anisotropically for the local km-per-degree difference between lat
    and lon, then translated to the center. Good enough at the scale of
    a single dark gap's reach (tens of km), not meant for anything
    global."""
    radius_lat_deg = radius_km / KM_PER_DEG_LAT
    radius_lon_deg = radius_km / _km_per_deg_lon(center_lat)
    circle = Point(0, 0).buffer(1.0, quad_segs=resolution)
    circle = scale(circle, xfact=radius_lon_deg, yfact=radius_lat_deg, origin=(0, 0))
    return translate(circle, xoff=center_lon, yoff=center_lat)


def dead_reckoned_envelope(entry: AISPoint, exit: AISPoint, max_speed_kn: float) -> dict:
    """The reachable set consistent with both ends of a dark gap: the
    intersection of the forward reach from entry and the backward reach
    to exit, each bounded by the vessel's plausible maximum speed. This
    is PLAN.md section 9's "propagate a cone that widens with time...
    and close it against the first position after the gap," implemented
    as the lens where those two reachable sets overlap."""
    duration_h = (exit.ts - entry.ts).total_seconds() / 3600.0
    max_speed_kmh = max_speed_kn * 1.852
    reach_km = max(max_speed_kmh * duration_h, 0.05)

    disk_from_entry = _circle_deg(entry.lat, entry.lon, reach_km)
    disk_from_exit = _circle_deg(exit.lat, exit.lon, reach_km)
    envelope = disk_from_entry.intersection(disk_from_exit)
    if envelope.is_empty:
        # reported positions implied a speed right at (or just past, from
        # rounding) the plausible maximum: fall back to the union so the
        # envelope still contains both endpoints instead of vanishing
        envelope = unary_union([disk_from_entry, disk_from_exit])
    return mapping(envelope)


def find_dark_gaps(points: list[AISPoint], min_gap_minutes: float, max_speed_kn: float) -> list[DarkGap]:
    """Flags inter-ping intervals longer than min_gap_minutes. That
    threshold is what keeps ordinary reporting dropouts from firing,
    per PLAN.md section 9: tune it against the observed dropout
    distribution, not against any single scenario."""
    gaps: list[DarkGap] = []
    for p0, p1 in zip(points, points[1:]):
        duration_min = (p1.ts - p0.ts).total_seconds() / 60.0
        if duration_min < min_gap_minutes:
            continue
        gaps.append(
            DarkGap(
                start=p0.ts,
                end=p1.ts,
                duration_min=duration_min,
                entry_point=(p0.lon, p0.lat),
                exit_point=(p1.lon, p1.lat),
                envelope=dead_reckoned_envelope(p0, p1, max_speed_kn),
            )
        )
    return gaps
