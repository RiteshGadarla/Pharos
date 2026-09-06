"""Offshore infrastructure overlap flag. See PLAN.md section 14.

If the origin envelope contains a fixed installation, a ship is not the
only thing that could have leaked. This module says so.

It does not eliminate any vessel and it does not accuse the
installation. It raises a flag with the position, and that flag exists
because the most damaging failure mode of an attribution engine is not
being wrong, it is being confidently wrong about a vessel when the
answer was a platform. Mumbai High makes this real for Indian waters
rather than hypothetical.

Cost is a static point layer plus one spatial query.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field as dataclass_field

import numpy as np
import xarray as xr

KM_PER_DEG_LAT = 111.32
M_PER_KM = 1000.0


@dataclass
class InfrastructureOverlap:
    flagged: bool
    mass_within_radius: float
    installations: list[dict] = dataclass_field(default_factory=list)
    statement: str = ""


def load_installations(path: str) -> list[dict]:
    """Reads the static offshore installation point layer.

    A missing layer is not an error: it means this case has no
    infrastructure data, which the caller reports as "not evaluated"
    rather than as "no infrastructure present". Silence and absence are
    different claims.
    """
    if not os.path.exists(path):
        return []
    with open(path) as f:
        collection = json.load(f)
    installations = []
    for feature in collection.get("features", []):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            continue
        lon, lat = geometry["coordinates"][:2]
        props = feature.get("properties", {})
        installations.append(
            {
                "name": props.get("name", "unnamed installation"),
                "type": props.get("type", "unknown"),
                "lon": float(lon),
                "lat": float(lat),
            }
        )
    return installations


def _mass_within_radius(field_ds: xr.Dataset, lat0: float, lon0: float, radius_m: float) -> float:
    """Total probability mass, summed over the whole time axis, inside a
    radius of one installation."""
    lats = field_ds["lat"].values
    lons = field_ds["lon"].values
    prob = field_ds["probability"].values.sum(axis=0)  # (lat, lon), summed over time

    radius_deg_lat = radius_m / M_PER_KM / KM_PER_DEG_LAT
    km_per_deg_lon = KM_PER_DEG_LAT * math.cos(math.radians(lat0)) or 1e-6
    radius_deg_lon = radius_m / M_PER_KM / km_per_deg_lon

    lon_grid, lat_grid = np.meshgrid(lons, lats)
    inside = ((lat_grid - lat0) / radius_deg_lat) ** 2 + ((lon_grid - lon0) / radius_deg_lon) ** 2 <= 1.0
    return float(prob[inside].sum())


def check_infrastructure_overlap(field_ds: xr.Dataset, infrastructure_config: dict) -> InfrastructureOverlap:
    """Flags the case if more than `mass_threshold` of the origin field's
    mass sits within `radius_m` of a known fixed installation."""
    path = infrastructure_config.get("layer_path", "")
    radius_m = float(infrastructure_config.get("radius_m", 5000.0))
    threshold = float(infrastructure_config.get("mass_threshold", 0.1))

    installations = load_installations(path)
    if not installations:
        return InfrastructureOverlap(
            flagged=False,
            mass_within_radius=0.0,
            statement=(
                "No offshore installation layer was available for this region, so "
                "infrastructure overlap was not evaluated. This is an absence of data, "
                "not a finding that no installation is present."
            ),
        )

    overlapping = []
    total_mass = 0.0
    for installation in installations:
        mass = _mass_within_radius(field_ds, installation["lat"], installation["lon"], radius_m)
        if mass > 0:
            overlapping.append({**installation, "mass": mass})
        total_mass += mass

    flagged = total_mass > threshold
    if flagged:
        names = ", ".join(
            f"{item['name']} at {item['lat']:.4f}, {item['lon']:.4f}" for item in overlapping
        )
        statement = (
            f"The origin envelope includes fixed infrastructure ({names}), holding "
            f"{total_mass:.1%} of the origin probability mass within {radius_m / M_PER_KM:.1f} km. "
            "Vessel attribution alone may be incomplete for this case. No vessel is "
            "eliminated by this flag and no installation is accused by it."
        )
    else:
        statement = (
            f"No fixed offshore installation holds more than {threshold:.1%} of the origin "
            f"probability mass within {radius_m / M_PER_KM:.1f} km "
            f"({len(installations)} installation(s) checked, {total_mass:.2%} of mass total)."
        )

    return InfrastructureOverlap(
        flagged=flagged,
        mass_within_radius=total_mass,
        installations=overlapping,
        statement=statement,
    )
