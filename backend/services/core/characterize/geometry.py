"""Slick geometry and backscatter features. See PLAN.md section 7.

Straightforward shapely and numpy, no cleverness needed, per the plan.
Backscatter stats are read from the source GeoTIFF directly (core
duplicates the two-line sigma0-to-dB conversion rather than importing
services.detection: stages communicate through files, never in-memory
coupling across the TensorFlow/core environment boundary).
"""

from __future__ import annotations

import math

import numpy as np
import rasterio
import rasterio.features
import shapely
from rasterio.warp import transform_geom
from scipy import ndimage
from shapely.geometry import mapping, shape
from shapely.geometry.polygon import Polygon

from services.core.schemas import Detection

LOCAL_SEA_RING_PX = 20


def sigma0_to_db(sigma0: np.ndarray) -> np.ndarray:
    return 10.0 * np.log10(np.clip(sigma0, 1e-6, None))


def _reproject_to_raster_crs(geometry: dict, raster_crs: str) -> Polygon:
    geom_src = transform_geom("EPSG:4326", raster_crs, geometry)
    return shape(geom_src)


def _rectangle_major_minor_and_angle(polygon: Polygon) -> tuple[float, float, float]:
    """Returns (major_length, minor_length, major_axis_deg) from the
    polygon's minimum rotated rectangle. major_axis_deg is 0-180."""
    mrr = shapely.minimum_rotated_rectangle(polygon)
    coords = list(mrr.exterior.coords)[:4]
    edge_a = math.dist(coords[0], coords[1])
    edge_b = math.dist(coords[1], coords[2])
    if edge_a >= edge_b:
        major_len, minor_len = edge_a, edge_b
        dx, dy = coords[1][0] - coords[0][0], coords[1][1] - coords[0][1]
    else:
        major_len, minor_len = edge_b, edge_a
        dx, dy = coords[2][0] - coords[1][0], coords[2][1] - coords[1][1]
    angle_deg = math.degrees(math.atan2(dy, dx)) % 180.0
    return major_len, minor_len, angle_deg


def _polygon_mask(polygon: Polygon, out_shape: tuple[int, int], transform) -> np.ndarray:
    return rasterio.features.geometry_mask(
        [mapping(polygon)], out_shape=out_shape, transform=transform, invert=True
    )


def _local_sea_mean_db(raster_db: np.ndarray, slick_mask: np.ndarray, ring_px: int = LOCAL_SEA_RING_PX) -> float:
    """Mean dB in a ring dilated outward from the slick, minus the slick
    itself, for the contrast_db feature."""
    dilated = ndimage.binary_dilation(slick_mask, iterations=ring_px)
    ring = dilated & ~slick_mask
    if not ring.any():
        return float("nan")
    return float(raster_db[ring].mean())


def compute_slick_features_dict(detection: Detection, source_geotiff_path: str) -> dict:
    """Computes the SlickFeatures fields for one Detection, minus age_band
    and age_reasoning (see characterize/age.py). Returns a plain dict so
    the caller can merge in the age classification before constructing
    the SlickFeatures model."""
    with rasterio.open(source_geotiff_path) as ds:
        sigma0 = ds.read(1).astype(np.float32)
        transform = ds.transform
        raster_crs = ds.crs.to_string()

    raster_db = sigma0_to_db(sigma0)
    polygon_src = _reproject_to_raster_crs(detection.geometry, raster_crs)

    area_km2 = polygon_src.area / 1e6
    perimeter_km = polygon_src.length / 1000.0
    complexity_ratio = perimeter_km / (2.0 * math.sqrt(math.pi * area_km2))

    major_len, minor_len, major_axis_deg = _rectangle_major_minor_and_angle(polygon_src)
    elongation = major_len / minor_len if minor_len > 0 else float("inf")

    slick_mask = _polygon_mask(polygon_src, raster_db.shape, transform)
    mean_backscatter_db = float(raster_db[slick_mask].mean()) if slick_mask.any() else float("nan")
    local_sea_db = _local_sea_mean_db(raster_db, slick_mask)
    contrast_db = mean_backscatter_db - local_sea_db

    return {
        "detection_id": detection.detection_id,
        "area_km2": area_km2,
        "perimeter_km": perimeter_km,
        "complexity_ratio": complexity_ratio,
        "major_axis_deg": major_axis_deg,
        "elongation": elongation,
        "mean_backscatter_db": mean_backscatter_db,
        "contrast_db": contrast_db,
    }
