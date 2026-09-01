"""Renders the SAR scene to a web-ready PNG for the frontend's map basemap.

The frontend map is a blank chart-paper canvas with no external tiles
(PLAN.md section 12: it has to work with the network cable unplugged).
Without a basemap the detection polygons float over empty water, which
reads as a mockup rather than as a satellite product. This module warps
the scene's VV band to EPSG:4326 and writes an 8-bit greyscale PNG that
deck.gl can drop under every other layer as a BitmapLayer.

Two things are deliberately separate from services/detection/render.py:

  * That module renders the *model input*, on the fixed dB window the
    model was trained against (config/pipeline.yaml render.db_window).
    Changing it to look nicer would silently change detection output.
  * This module renders a *display* product, on a percentile stretch
    picked for contrast on a projector. The stretch it used is returned
    with the image and is shown in the UI, so the picture on screen is
    never presented as the calibrated data.
"""

from __future__ import annotations

import numpy as np
import rasterio
from PIL import Image
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject, transform_bounds

from services.detection.render import sigma0_to_db

WGS84 = "EPSG:4326"

# Display stretch, in dB relative to the scene's own sea level (its
# median, since a marine scene is overwhelmingly sea).
#
# A plain percentile stretch is wrong here and looks it: a slick covers
# well under 1% of the scene, so p2/p98 lands entirely inside the sea's
# own speckle distribution and renders the sea as full-range black and
# white noise with the slick a flat black hole. Anchoring on the sea
# instead puts the sea in the upper grey range with its speckle visible
# but calm, and gives the slick 10 dB of room below it, so the slick's
# internal structure and its feathered edges survive.
SEA_RELATIVE_WINDOW_DB = (-10.0, 4.0)


def _warp_to_wgs84(db: np.ndarray, src_transform, src_crs: str) -> tuple[np.ndarray, list[float]]:
    """Warps a dB array to EPSG:4326, returning the warped array (NaN
    outside the source footprint) and its [west, south, east, north]
    bounds."""
    height, width = db.shape
    src_bounds = rasterio.transform.array_bounds(height, width, src_transform)
    dst_transform, dst_width, dst_height = calculate_default_transform(
        CRS.from_string(src_crs), CRS.from_string(WGS84), width, height, *src_bounds
    )

    dst = np.full((dst_height, dst_width), np.nan, dtype=np.float32)
    reproject(
        source=db.astype(np.float32),
        destination=dst,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=WGS84,
        src_nodata=np.nan,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )

    west, south, east, north = rasterio.transform.array_bounds(dst_height, dst_width, dst_transform)
    return dst, [west, south, east, north]


def _stretch_to_rgba(db: np.ndarray, window_db: tuple[float, float]) -> tuple[np.ndarray, tuple[float, float]]:
    """Clips to a window anchored on the scene's sea level, stretches to
    0-255 grey, and puts the warp's empty corners in the alpha channel so
    they read as chart paper rather than as a black rectangle."""
    valid = np.isfinite(db)
    if not valid.any():
        raise ValueError("scene has no valid pixels to render")

    sea_level = float(np.median(db[valid]))
    lo, hi = sea_level + window_db[0], sea_level + window_db[1]

    grey = np.zeros(db.shape, dtype=np.uint8)
    stretched = (np.clip(db, lo, hi) - lo) / (hi - lo) * 255.0
    grey[valid] = stretched[valid].astype(np.uint8)

    rgba = np.dstack([grey, grey, grey, np.where(valid, 255, 0).astype(np.uint8)])
    return rgba, (lo, hi)


def render_scene_preview(
    scene_path: str,
    out_path: str,
    window_db: tuple[float, float] = SEA_RELATIVE_WINDOW_DB,
) -> dict:
    """Writes a WGS84 greyscale PNG of the scene's VV band to out_path.

    Returns the metadata the frontend needs to place it: the image
    bounds in lon/lat, its pixel size, and the dB window the display
    stretch actually used.
    """
    with rasterio.open(scene_path) as ds:
        sigma0 = ds.read(1).astype(np.float32)
        src_transform = ds.transform
        src_crs = ds.crs.to_string()
        native_bounds = list(transform_bounds(ds.crs, WGS84, *ds.bounds))

    db = sigma0_to_db(sigma0)
    warped, bounds = _warp_to_wgs84(db, src_transform, src_crs)
    rgba, (lo, hi) = _stretch_to_rgba(warped, window_db)

    Image.fromarray(rgba, mode="RGBA").save(out_path, optimize=True)

    return {
        "path": out_path,
        # deck.gl BitmapLayer bounds order: [west, south, east, north]
        "bounds": bounds,
        "native_bounds": native_bounds,
        "width": int(rgba.shape[1]),
        "height": int(rgba.shape[0]),
        "display_db_window": [round(lo, 2), round(hi, 2)],
        "note": (
            f"VV backscatter, warped to EPSG:4326 and stretched for display over "
            f"{lo:.1f} to {hi:.1f} dB (the scene's own sea level "
            f"{window_db[0]:+g} to {window_db[1]:+g} dB). Display product only: "
            "detection ran on the calibrated scene over the fixed dB window in "
            "config/pipeline.yaml, not on this image."
        ),
    }
