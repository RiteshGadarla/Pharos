"""Ship target extraction from the stitched softmax. See PLAN.md section 11.

The model's Ships channel is not decoration. Every hull it finds is an
observation by a second, independent sensor: Sentinel-1 photographed
something at a position and an instant, whether or not AIS reported it.
That is what turns a dark vessel from an inference about missing data
into a positive observation, and it is what crosscheck/radar.py
consumes.

What this module does NOT do, and must never be made to do: assert that
an unmatched target is guilty of anything. Sentinel-1 misses small
vessels at GRD resolution, and vessels below AIS carriage requirements,
fishing craft and buoys all show up here. The caveats belong with the
output, so they are stated in the dossier and repeated in the docs.
"""

from __future__ import annotations

import numpy as np
from affine import Affine
from rasterio.warp import transform_geom
from scipy import ndimage
from shapely.geometry import shape

from services.core.schemas import ShipTarget


def extract_ship_targets(
    softmax: np.ndarray,
    transform: Affine,
    src_crs: str,
    classes: list[str],
    scene_id: str,
    backscatter_db: np.ndarray | None = None,
    min_pixel_area: int = 4,
    max_pixel_area: int = 20000,
    dst_crs: str = "EPSG:4326",
) -> list[ShipTarget]:
    """Connected components of the Ships class, filtered by area bounds,
    georeferenced to EPSG:4326.

    min_pixel_area rejects speckle, which at C-band is the dominant
    false positive. max_pixel_area rejects the other failure mode:
    mis-segmented land, a platform, or a large slick edge picked up as
    one enormous "ship".

    backscatter_db is the rendered dB image the softmax came from. When
    given, each target carries its own mean backscatter, which is what
    lets the dossier report unmatched target sizes and brightnesses
    rather than just a count.
    """
    ships_index = classes.index("ships")
    ship_mask = np.argmax(softmax, axis=-1) == ships_index
    if not ship_mask.any():
        return []

    labels, n_labels = ndimage.label(ship_mask)
    targets: list[ShipTarget] = []

    for label_value in range(1, n_labels + 1):
        component = labels == label_value
        pixel_area = int(component.sum())
        if pixel_area < min_pixel_area or pixel_area > max_pixel_area:
            continue

        rows, cols = np.nonzero(component)
        row_c = float(rows.mean()) + 0.5
        col_c = float(cols.mean()) + 0.5
        x_src, y_src = transform @ (col_c, row_c)
        lon, lat = _to_geographic(x_src, y_src, src_crs, dst_crs)

        if backscatter_db is not None:
            mean_db = float(np.mean(backscatter_db[component]))
        else:
            mean_db = float("nan")

        targets.append(
            ShipTarget(
                target_id=f"{scene_id}-ship-{len(targets):03d}",
                scene_id=scene_id,
                centroid=(lon, lat),
                pixel_area=pixel_area,
                mean_backscatter_db=mean_db,
                matched_mmsi=None,  # crosscheck/radar.py fills this in
            )
        )
    return targets


def _to_geographic(x: float, y: float, src_crs: str, dst_crs: str) -> tuple[float, float]:
    geom = transform_geom(src_crs, dst_crs, {"type": "Point", "coordinates": (x, y)})
    lon, lat = shape(geom).coords[0]
    return float(lon), float(lat)


def targets_to_feature_collection(targets: list[ShipTarget]) -> dict:
    """GeoJSON for the frontend's radar target layer and the dossier map."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": list(t.centroid)},
                "properties": {
                    "target_id": t.target_id,
                    "scene_id": t.scene_id,
                    "pixel_area": t.pixel_area,
                    "mean_backscatter_db": t.mean_backscatter_db,
                    "matched_mmsi": t.matched_mmsi,
                    "match_distance_m": t.match_distance_m,
                    "match_confidence": t.match_confidence,
                },
            }
            for t in targets
        ],
    }
