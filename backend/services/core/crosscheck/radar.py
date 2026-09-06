"""SAR ship target to AIS association. See PLAN.md section 11.

This is the stage that converts a dark vessel from an inference about
missing data into an independent sensor observation. Every ShipTarget
the detector found is matched against the AIS picture interpolated to
the scene's acquisition instant. What is left over is a hull
Sentinel-1 photographed that AIS did not report.

Three caveats travel with every output of this module, and they are
restated in the dossier because a jury will find them otherwise:

1. Sentinel-1 ship detection at GRD resolution misses small vessels.
2. Not every unmatched target is evasion. Vessels below AIS carriage
   requirements, fishing craft and buoys all appear. This module
   reports count, size and position; it never asserts that unmatched
   equals guilty.
3. The match is at acquisition time only, which is a single instant.
   That cuts both ways, and the code takes it seriously: an unmatched
   target is only ever attributed to a vessel that was dark at that
   same instant, never to one whose gap had already closed.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field as dataclass_field

import numpy as np
import xarray as xr
from shapely.geometry import Point, shape

from services.core.ais.tracks import haversine_km, position_at
from services.core.schemas import AISTrack, ShipTarget

M_PER_KM = 1000.0


@dataclass
class RadarCrossCheck:
    """The result of one scene's cross check.

    unmatched is the finding. matched is the control: a cross check
    that matches nothing is a broken matcher, not a fleet of dark
    vessels, and reporting both is what makes the difference visible.
    """

    targets: list[ShipTarget]
    matched: list[ShipTarget] = dataclass_field(default_factory=list)
    unmatched: list[ShipTarget] = dataclass_field(default_factory=list)
    # target_id -> mmsi whose dark envelope contains that target
    envelope_hits: dict[str, list[str]] = dataclass_field(default_factory=dict)
    # target_id -> origin field probability at that target's cell
    field_mass: dict[str, float] = dataclass_field(default_factory=dict)

    def unmatched_in_field(self, eps: float) -> list[ShipTarget]:
        """Unmatched targets sitting in a field cell above eps. This is
        half the DARK_CONFIRMED test in PLAN.md section 12."""
        return [t for t in self.unmatched if self.field_mass.get(t.target_id, 0.0) > eps]

    def support_for(self, mmsi: str) -> tuple[ShipTarget | None, float]:
        """The best unmatched target backing this vessel's dark period,
        and the origin field mass at it. Used by F8."""
        best: ShipTarget | None = None
        best_mass = 0.0
        for target in self.unmatched:
            if mmsi not in self.envelope_hits.get(target.target_id, []):
                continue
            mass = self.field_mass.get(target.target_id, 0.0)
            if best is None or mass > best_mass:
                best, best_mass = target, mass
        return best, best_mass


def match_confidence(distance_m: float, radius_m: float) -> float:
    """Falls linearly from 1.0 at zero distance to 0 at the match
    radius, so a marginal association is scored as marginal rather than
    counted as certain."""
    if radius_m <= 0:
        return 0.0
    return float(np.clip(1.0 - distance_m / radius_m, 0.0, 1.0))


def match_targets_to_ais(
    targets: list[ShipTarget],
    tracks: list[AISTrack],
    acquired_at: datetime.datetime,
    radius_m: float,
) -> list[ShipTarget]:
    """Greedy nearest assignment with a distance cap.

    Greedy rather than optimal (Hungarian) on purpose: at the density of
    a single scene the two agree, and greedy is inspectable, which
    matters more here than a fractional improvement nobody can audit.
    Each MMSI is claimed at most once, so two targets cannot both be
    explained by the same broadcasting vessel.
    """
    candidates: list[tuple[float, int, str]] = []  # distance_m, target index, mmsi
    for track in tracks:
        pos = position_at(track, acquired_at)
        if pos is None:
            # No position at the acquisition instant, which for a vessel
            # in a dark gap is exactly the situation this stage exists
            # for: it stays unavailable to claim any target.
            continue
        lat, lon = pos
        for i, target in enumerate(targets):
            t_lon, t_lat = target.centroid
            distance_m = haversine_km(lat, lon, t_lat, t_lon) * M_PER_KM
            if distance_m <= radius_m:
                candidates.append((distance_m, i, track.mmsi))

    candidates.sort(key=lambda c: c[0])
    claimed_targets: set[int] = set()
    claimed_mmsi: set[str] = set()
    matched: list[ShipTarget] = list(targets)

    for distance_m, i, mmsi in candidates:
        if i in claimed_targets or mmsi in claimed_mmsi:
            continue
        claimed_targets.add(i)
        claimed_mmsi.add(mmsi)
        matched[i] = matched[i].model_copy(
            update={
                "matched_mmsi": mmsi,
                "match_distance_m": distance_m,
                "match_confidence": match_confidence(distance_m, radius_m),
            }
        )
    return matched


def _field_mass_at(field_ds: xr.Dataset, lat: float, lon: float) -> float:
    """The largest probability this position holds at any timestep.

    Across time, not at one instant: a ship target is observed at the
    acquisition instant, but the question F8 asks is whether that hull
    was sitting where the spill could have started at any point in the
    origin window.
    """
    column = field_ds["probability"].sel(lat=lat, lon=lon, method="nearest")
    return float(np.max(column.values))


def run_cross_check(
    targets: list[ShipTarget],
    tracks: list[AISTrack],
    field_ds: xr.Dataset,
    acquired_at: datetime.datetime,
    radar_config: dict,
) -> RadarCrossCheck:
    """Full cross check: match, split matched from unmatched, then test
    each unmatched target against every dark envelope and against the
    origin field."""
    radius_m = float(radar_config.get("match_radius_m", 1500.0))
    resolved = match_targets_to_ais(targets, tracks, acquired_at, radius_m)

    matched = [t for t in resolved if t.matched_mmsi is not None]
    unmatched = [t for t in resolved if t.matched_mmsi is None]

    envelope_hits: dict[str, list[str]] = {}
    field_mass: dict[str, float] = {}
    for target in unmatched:
        lon, lat = target.centroid
        point = Point(lon, lat)
        # A dark envelope only counts if the vessel was dark AT the
        # acquisition instant. The target is a single observation at a
        # single moment: a hull in the image cannot be a vessel whose
        # transponder came back on hours earlier, however well the
        # envelope of that old gap happens to contain the position.
        # Without this the check degenerates, because a dead-reckoned
        # envelope grows at the vessel's plausible maximum speed and
        # after an hour it is wider than the whole origin field.
        hits = [
            track.mmsi
            for track in tracks
            for gap in track.dark_gaps
            if gap.start <= acquired_at <= gap.end and shape(gap.envelope).contains(point)
        ]
        envelope_hits[target.target_id] = sorted(set(hits))
        field_mass[target.target_id] = _field_mass_at(field_ds, lat, lon)

    return RadarCrossCheck(
        targets=resolved,
        matched=matched,
        unmatched=unmatched,
        envelope_hits=envelope_hits,
        field_mass=field_mass,
    )
