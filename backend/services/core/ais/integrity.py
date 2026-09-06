"""AIS self-report integrity checks, F7. See PLAN.md section 10.

AIS is spoofable, not merely switchable. A vessel that wants to be
somewhere else on the screen does not have to go dark: it can report a
position it is not at, reuse another vessel's MMSI, or change its
static data mid passage. Dark gap detection alone answers none of that,
so this module exists to make "AIS can be spoofed, not just switched
off" a scored factor instead of a shrug.

Every flag carries a severity in 0 to 1 from config/scoring.yaml, and
scoring/factors.py aggregates them. Nothing here eliminates a vessel:
a single flag is often a data quality artifact rather than evasion, and
the elimination rules in PLAN.md section 12 are the only three that
drop anything.
"""

from __future__ import annotations

import datetime
from collections import defaultdict

from services.core.ais.tracks import haversine_km
from services.core.schemas import AISPoint, AISTrack, IntegrityFlag

KN_PER_KMH = 1.0 / 1.852

# Vessel classes that carry an IMO number under SOLAS. A missing IMO on
# one of these is a flag; a fishing boat without one is simply a fishing
# boat, so it is not.
IMO_BEARING_TYPES = {"tanker", "cargo", "passenger"}

DEFAULT_SEVERITIES = {
    "no_imo": 0.3,
    "implied_speed": 0.8,
    "static_change": 0.5,
    "mmsi_reuse": 0.9,
    "position_jump": 0.7,
}


def _severity(kind: str, integrity_config: dict) -> float:
    return float(integrity_config.get("severities", DEFAULT_SEVERITIES).get(kind, DEFAULT_SEVERITIES[kind]))


def check_implied_speed(track: AISTrack, integrity_config: dict) -> list[IntegrityFlag]:
    """Implied speed between consecutive pings beyond the vessel's
    plausible maximum. A hull that appears to have made 60 knots
    between two reports did not: one of the two positions is wrong."""
    max_kn = float(integrity_config.get("implied_speed_max_kn", 30.0))
    severity = _severity("implied_speed", integrity_config)
    flags: list[IntegrityFlag] = []
    for p0, p1 in zip(track.points, track.points[1:]):
        hours = (p1.ts - p0.ts).total_seconds() / 3600.0
        if hours <= 0:
            continue
        implied_kn = haversine_km(p0.lat, p0.lon, p1.lat, p1.lon) / hours * KN_PER_KMH
        if implied_kn > max_kn:
            flags.append(
                IntegrityFlag(
                    kind="implied_speed",
                    at=p1.ts,
                    detail=(
                        f"Consecutive positions imply {implied_kn:.1f} knots, above the "
                        f"{max_kn:.0f} knot plausible maximum for this vessel."
                    ),
                    severity=severity,
                )
            )
    return flags


def check_position_jump(track: AISTrack, integrity_config: dict) -> list[IntegrityFlag]:
    """A position discontinuity inconsistent with the vessel's own
    reported course and speed.

    Distinct from implied_speed: a vessel can jump a distance it could
    physically have covered, while having reported a course and a speed
    that say it went somewhere else entirely. That mismatch between the
    self-reported dynamics and the self-reported positions is the
    signature of a fabricated track.
    """
    tolerance_km = float(integrity_config.get("position_jump_tolerance_km", 5.0))
    severity = _severity("position_jump", integrity_config)
    flags: list[IntegrityFlag] = []
    for p0, p1 in zip(track.points, track.points[1:]):
        hours = (p1.ts - p0.ts).total_seconds() / 3600.0
        if hours <= 0:
            continue
        actual_km = haversine_km(p0.lat, p0.lon, p1.lat, p1.lon)
        expected_km = p0.sog * 1.852 * hours
        if abs(actual_km - expected_km) > tolerance_km:
            flags.append(
                IntegrityFlag(
                    kind="position_jump",
                    at=p1.ts,
                    detail=(
                        f"Moved {actual_km:.1f} km between reports while reporting "
                        f"{p0.sog:.1f} knots, which accounts for {expected_km:.1f} km."
                    ),
                    severity=severity,
                )
            )
    return flags


def check_no_imo(track: AISTrack, imo_by_mmsi: dict[str, str] | None, integrity_config: dict) -> list[IntegrityFlag]:
    """A vessel class that should carry an IMO number, broadcasting
    without one."""
    if imo_by_mmsi is None or track.vessel_type not in IMO_BEARING_TYPES:
        return []
    if imo_by_mmsi.get(track.mmsi):
        return []
    at = track.points[0].ts if track.points else datetime.datetime.now(datetime.timezone.utc)
    return [
        IntegrityFlag(
            kind="no_imo",
            at=at,
            detail=(
                f"Reported as a {track.vessel_type} but broadcasts no IMO number, "
                "which a vessel of this class is required to carry."
            ),
            severity=_severity("no_imo", integrity_config),
        )
    ]


def check_static_change(track: AISTrack, static_reports: list[dict] | None, integrity_config: dict) -> list[IntegrityFlag]:
    """Voyage or static data changing mid passage: a vessel that renames
    itself, changes its declared type or rewrites its destination
    between two ports."""
    if not static_reports or len(static_reports) < 2:
        return []
    severity = _severity("static_change", integrity_config)
    flags: list[IntegrityFlag] = []
    watched = ("vessel_name", "vessel_type", "destination", "call_sign")
    for prev, current in zip(static_reports, static_reports[1:]):
        changed = [k for k in watched if k in prev and k in current and prev[k] != current[k]]
        if not changed:
            continue
        flags.append(
            IntegrityFlag(
                kind="static_change",
                at=current.get("ts", track.points[-1].ts if track.points else datetime.datetime.now(datetime.timezone.utc)),
                detail=(
                    "Static or voyage data changed mid passage: "
                    + ", ".join(f"{k} {prev[k]!r} to {current[k]!r}" for k in changed)
                ),
                severity=severity,
            )
        )
    return flags


def check_mmsi_reuse(tracks: list[AISTrack], integrity_config: dict) -> dict[str, list[IntegrityFlag]]:
    """The same MMSI reported from two places within a physically
    impossible interval. Checked across the whole fleet rather than per
    track, because that is the only level at which it is visible."""
    max_kn = float(integrity_config.get("implied_speed_max_kn", 30.0))
    severity = _severity("mmsi_reuse", integrity_config)

    by_mmsi: dict[str, list[AISPoint]] = defaultdict(list)
    for track in tracks:
        by_mmsi[track.mmsi].extend(track.points)

    flags: dict[str, list[IntegrityFlag]] = defaultdict(list)
    for mmsi, points in by_mmsi.items():
        ordered = sorted(points, key=lambda p: p.ts)
        for p0, p1 in zip(ordered, ordered[1:]):
            hours = (p1.ts - p0.ts).total_seconds() / 3600.0
            distance_km = haversine_km(p0.lat, p0.lon, p1.lat, p1.lon)
            reachable_km = max_kn * 1.852 * max(hours, 0.0)
            if distance_km > reachable_km + 1.0:
                flags[mmsi].append(
                    IntegrityFlag(
                        kind="mmsi_reuse",
                        at=p1.ts,
                        detail=(
                            f"MMSI {mmsi} reported {distance_km:.1f} km apart within "
                            f"{hours * 60:.0f} minutes, which no single hull can cover."
                        ),
                        severity=severity,
                    )
                )
    return dict(flags)


def annotate_integrity(
    tracks: list[AISTrack],
    integrity_config: dict,
    imo_by_mmsi: dict[str, str] | None = None,
    static_reports_by_mmsi: dict[str, list[dict]] | None = None,
) -> list[AISTrack]:
    """Runs every check and returns tracks with integrity_flags filled in.

    Returns copies rather than mutating, so a caller can score with and
    without integrity flags (which is exactly what the validation
    harness's F7 comparison needs) without the two runs interfering.
    """
    reuse_flags = check_mmsi_reuse(tracks, integrity_config)
    annotated: list[AISTrack] = []
    for track in tracks:
        flags: list[IntegrityFlag] = []
        flags.extend(check_implied_speed(track, integrity_config))
        flags.extend(check_position_jump(track, integrity_config))
        flags.extend(check_no_imo(track, imo_by_mmsi, integrity_config))
        flags.extend(
            check_static_change(track, (static_reports_by_mmsi or {}).get(track.mmsi), integrity_config)
        )
        flags.extend(reuse_flags.get(track.mmsi, []))
        flags.sort(key=lambda f: f.at)
        annotated.append(track.model_copy(update={"integrity_flags": flags}))
    return annotated
