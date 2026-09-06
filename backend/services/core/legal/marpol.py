"""MARPOL Annex I evaluation. See PLAN.md section 13.

This bridges detection to enforcement, which is the step almost nobody
takes: a ranked suspect list stops at the screen, while a condition by
condition assessment is something an investigator can act on.

HARD RULE, and it is enforced by the shape of the output rather than by
good intentions: this layer never outputs a determination of illegality.
It reports which Annex I conditions the reconstructed behaviour appears
not to satisfy, with the assumptions printed. Oil content in parts per
million is not observable from satellite, so `conditions_met` can never
be asserted on that basis and the code below does not attempt it: the
only way to reach `conditions_met` here is for every checkable condition
to be satisfied, and the assessment says explicitly that the ppm
condition was not evaluated.
"""

from __future__ import annotations

import datetime
import json
import os
from dataclasses import dataclass

import numpy as np
import xarray as xr
from shapely.geometry import Point, shape

from services.core.ais.tracks import haversine_km, position_at
from services.core.schemas import AISTrack, MarpolAssessment, SlickFeatures

KM_PER_NM = 1.852
UM_PER_M = 1e6
L_PER_M3 = 1000.0


@dataclass(frozen=True)
class StaticLayers:
    """The two geographic layers the assessment needs. Both are small
    and committed, so this runs with the network cable unplugged."""

    coastline: list  # shapely geometries
    special_areas: list


def load_static_layers(marpol_config: dict) -> StaticLayers:
    return StaticLayers(
        coastline=_load_geometries(marpol_config.get("coastline_path", "")),
        special_areas=_load_geometries(marpol_config.get("special_areas_path", "")),
    )


def _load_geometries(path: str) -> list:
    if not path or not os.path.exists(path):
        return []
    with open(path) as f:
        collection = json.load(f)
    return [shape(feature["geometry"]) for feature in collection.get("features", []) if feature.get("geometry")]


def _field_time_bounds(field_ds: xr.Dataset) -> tuple[datetime.datetime, datetime.datetime]:
    import pandas as pd

    times = field_ds["time"].values
    return pd.Timestamp(times.min()).to_pydatetime(), pd.Timestamp(times.max()).to_pydatetime()


def track_inside_window(track: AISTrack, field_ds: xr.Dataset) -> list[tuple[float, float, datetime.datetime]]:
    """Interpolated positions at each field timestep where the vessel had
    one. This is the discharge window as far as the reconstruction can
    see it."""
    import pandas as pd

    positions = []
    for t64 in field_ds["time"].values:
        t = pd.Timestamp(t64).to_pydatetime()
        pos = position_at(track, t)
        if pos is not None:
            positions.append((pos[0], pos[1], t))
    return positions


def track_length_nm(positions: list[tuple[float, float, datetime.datetime]]) -> float:
    total_km = sum(
        haversine_km(a[0], a[1], b[0], b[1]) for a, b in zip(positions, positions[1:])
    )
    return total_km / KM_PER_NM


def min_distance_to_land_nm(positions: list[tuple[float, float, datetime.datetime]], coastline: list) -> float | None:
    """Nearest approach of the reconstructed track to the coastline
    layer, in nautical miles. None when no coastline layer is loaded:
    an unmeasured distance is not a satisfied condition."""
    if not coastline or not positions:
        return None
    KM_PER_DEG = 111.32
    best = None
    for lat, lon, _ in positions:
        point = Point(lon, lat)
        for geom in coastline:
            distance_deg = point.distance(geom)
            distance_nm = distance_deg * KM_PER_DEG / KM_PER_NM
            if best is None or distance_nm < best:
                best = distance_nm
    return best


def in_special_area(positions: list[tuple[float, float, datetime.datetime]], special_areas: list) -> bool | None:
    if not special_areas:
        return None
    for lat, lon, _ in positions:
        point = Point(lon, lat)
        if any(area.contains(point) for area in special_areas):
            return True
    return False


def is_en_route(track: AISTrack, positions: list[tuple[float, float, datetime.datetime]], min_sog_kn: float) -> bool | None:
    """Whether the vessel was under way throughout the window.

    "Proceeding en route" is not a speed in the regulation, it means
    under way on a passage. This is an operational proxy and it is
    printed as an assumption on every assessment rather than hidden.
    """
    from services.core.ais.tracks import course_and_speed_at

    speeds = []
    for _, _, t in positions:
        cs = course_and_speed_at(track, t)
        if cs is not None:
            speeds.append(cs[1])
    if not speeds:
        return None
    return bool(np.min(speeds) >= min_sog_kn)


def discharge_band_l_per_nm(
    slick_features: SlickFeatures,
    track_nm: float,
    thickness_band_um: tuple[float, float],
) -> tuple[float, float] | None:
    """Slick area times a thickness band gives a volume band; divided by
    the track length inside the field it gives litres per nautical mile
    as a band.

    A band, never a scalar, and the schema enforces that. SAR sees that
    a damping film is present, never how thick it is, so the volume
    behind this rate is only ever known to an order of magnitude.
    """
    if track_nm <= 0 or slick_features.area_km2 <= 0:
        return None
    area_m2 = slick_features.area_km2 * 1e6
    lo_um, hi_um = thickness_band_um
    lo_l = area_m2 * (lo_um / UM_PER_M) * L_PER_M3
    hi_l = area_m2 * (hi_um / UM_PER_M) * L_PER_M3
    return (lo_l / track_nm, hi_l / track_nm)


def assess(
    track: AISTrack,
    field_ds: xr.Dataset,
    slick_features: SlickFeatures,
    marpol_config: dict,
    layers: StaticLayers | None = None,
) -> MarpolAssessment:
    """Evaluates the Annex I conditions that are checkable from a
    reconstructed track, for one vessel."""
    layers = layers or load_static_layers(marpol_config)
    assumptions = list(marpol_config.get("assumptions", []))

    positions = track_inside_window(track, field_ds)
    if not positions:
        return MarpolAssessment(
            mmsi=track.mmsi,
            flag="insufficient_data",
            assumptions=assumptions
            + ["No reconstructed position fell inside the origin field's time window, so no condition could be evaluated."],
        )

    is_tanker = track.vessel_type == "tanker"
    limits = marpol_config["cargo_area"] if is_tanker else marpol_config["machinery_space"]
    min_distance_nm = float(limits["min_distance_to_land_nm"])

    en_route = is_en_route(track, positions, float(marpol_config.get("en_route_min_sog_kn", 4.0)))
    distance_nm = min_distance_to_land_nm(positions, layers.coastline)
    special = in_special_area(positions, layers.special_areas)
    band = discharge_band_l_per_nm(
        slick_features, track_length_nm(positions), tuple(marpol_config["thickness_band_um"])
    )

    unmet: list[str] = []
    unknown: list[str] = []

    if en_route is False:
        unmet.append(
            f"The vessel was not proceeding en route throughout the window "
            f"(speed fell below {marpol_config.get('en_route_min_sog_kn', 4.0)} knots)."
        )
    elif en_route is None:
        unknown.append("en route status")

    if distance_nm is None:
        unknown.append("distance to nearest land")
    elif distance_nm < min_distance_nm:
        unmet.append(
            f"The track came within {distance_nm:.1f} nautical miles of land, inside the "
            f"{min_distance_nm:.0f} nautical mile limit for this discharge category."
        )

    if special is None:
        unknown.append("special area status")
    elif special and is_tanker:
        unmet.append(
            "The track passed inside a MARPOL special area, where cargo area discharge "
            "is not permitted at all."
        )

    if is_tanker and band is not None:
        max_rate = float(limits["max_discharge_l_per_nm"])
        if band[0] > max_rate:
            unmet.append(
                f"The estimated instantaneous discharge rate band, {band[0]:.0f} to "
                f"{band[1]:.0f} litres per nautical mile, lies entirely above the "
                f"{max_rate:.0f} litre per nautical mile limit."
            )
        elif band[1] > max_rate:
            unknown.append(
                f"instantaneous discharge rate (band {band[0]:.0f} to {band[1]:.0f} "
                f"litres per nautical mile spans the {max_rate:.0f} limit)"
            )

    assumptions.append(
        "Oil content in parts per million was not evaluated and cannot be, so no "
        "assessment here can conclude that a discharge was permitted."
    )
    if unknown:
        assumptions.append("Not evaluated for want of data: " + ", ".join(unknown) + ".")

    if unmet:
        flag = "conditions_not_met"
        assumptions.append("Conditions that appear unsatisfied: " + " ".join(unmet))
    elif unknown:
        flag = "insufficient_data"
    else:
        # Every checkable condition is satisfied. This is still not a
        # finding of legality: the ppm condition was never evaluated,
        # and the assumption above says so on the page.
        flag = "conditions_met"

    return MarpolAssessment(
        mmsi=track.mmsi,
        en_route=en_route,
        distance_to_land_nm=distance_nm,
        in_special_area=special,
        est_discharge_l_per_nm=band,
        flag=flag,
        assumptions=assumptions,
    )
