"""Vectorises the stitched softmax field into GeoJSON Detection records.
See PLAN.md section 5, "Georeferencing", and the Detection contract in
section 4 (services/core/schemas.py).

The model's own class names (background, oil_spill, ships, look_alike,
wakes) are not the schema's class_name values (background, oil,
look_alike, ship, wake), so MODEL_TO_SCHEMA_CLASS is the one place that
mapping happens.
"""

from __future__ import annotations

from affine import Affine
import numpy as np
import rasterio.features
from rasterio.warp import transform_geom
from scipy import ndimage
from shapely.geometry import mapping, shape

MODEL_TO_SCHEMA_CLASS = {
    "background": "background",
    "oil_spill": "oil",
    "ships": "ship",
    "look_alike": "look_alike",
    "wakes": "wake",
}


def polygonize_class(
    softmax: np.ndarray,
    transform: Affine,
    src_crs: str,
    class_index: int,
    class_name: str,
    min_area_km2: float,
    simplify_tolerance_deg: float = 0.0001,
    dst_crs: str = "EPSG:4326",
) -> list[dict]:
    """Vectorises one class from an averaged softmax field into detection
    dicts, reprojected to dst_crs.

    Assumes src_crs units are metres, true for a terrain-corrected
    Sentinel-1 product, since area is computed in the source CRS before
    reprojecting to geographic coordinates.
    """
    class_mask = np.argmax(softmax, axis=-1) == class_index
    if not class_mask.any():
        return []

    labels, _ = ndimage.label(class_mask)

    detections = []
    shapes_gen = rasterio.features.shapes(labels.astype(np.int32), mask=class_mask, transform=transform)
    for geom, label_value in shapes_gen:
        label_value = int(label_value)
        if label_value == 0:
            continue

        component_mask = labels == label_value
        pixel_area = int(component_mask.sum())
        mean_prob = float(softmax[..., class_index][component_mask].mean())

        poly_src = shape(geom)
        area_km2 = poly_src.area / 1e6
        if area_km2 < min_area_km2:
            continue

        geom_4326 = transform_geom(src_crs, dst_crs, geom)
        poly_4326 = shape(geom_4326).simplify(simplify_tolerance_deg, preserve_topology=True)

        detections.append(
            {
                "class_name": class_name,
                "geometry": mapping(poly_4326),
                "mean_class_prob": mean_prob,
                "pixel_area": pixel_area,
                "area_km2": area_km2,
            }
        )
    return detections


def to_feature_collection(detections: list[dict], scene_id: str) -> dict:
    features = []
    for i, det in enumerate(detections):
        features.append(
            {
                "type": "Feature",
                "geometry": det["geometry"],
                "properties": {
                    "detection_id": f"{scene_id}-{det['class_name']}-{i:03d}",
                    "scene_id": scene_id,
                    "class_name": det["class_name"],
                    "mean_class_prob": det["mean_class_prob"],
                    "pixel_area": det["pixel_area"],
                    "area_km2": det["area_km2"],
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def detect_oil(
    softmax: np.ndarray,
    transform: Affine,
    src_crs: str,
    classes: list[str],
    min_area_km2: float,
    scene_id: str,
) -> dict:
    """End to end for the oil class: polygonize, map to the schema class
    name, wrap as a GeoJSON FeatureCollection. This is what PLAN.md
    section 14's P2 acceptance test exercises."""
    oil_index = classes.index("oil_spill")
    detections = polygonize_class(
        softmax,
        transform,
        src_crs,
        class_index=oil_index,
        class_name=MODEL_TO_SCHEMA_CLASS["oil_spill"],
        min_area_km2=min_area_km2,
    )
    return to_feature_collection(detections, scene_id)
