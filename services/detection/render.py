"""SAR to model-input rendering. See PLAN.md section 5, "the rendering trap".

The model expects an 8-bit visual product like its training data, not
calibrated SAR. Feeding raw DN or unclipped dB degrades output silently
rather than erroring, so this module is the one place that conversion
happens.
"""

from __future__ import annotations

import numpy as np
import rasterio
from affine import Affine


def read_vv_band(path: str) -> tuple[np.ndarray, Affine, str]:
    """Reads band 1 (VV) of a GeoTIFF, assumed to be calibrated sigma0 (linear power).

    Returns the raw band, its affine transform and its CRS as an EPSG string.
    """
    with rasterio.open(path) as ds:
        band = ds.read(1).astype(np.float32)
        transform = ds.transform
        crs = ds.crs.to_string()
    return band, transform, crs


def sigma0_to_db(sigma0: np.ndarray) -> np.ndarray:
    """Converts calibrated linear sigma0 to dB. Clips to a tiny positive floor
    first so log10 never sees zero or negative values from nodata pixels."""
    floor = 1e-6
    return 10.0 * np.log10(np.clip(sigma0, floor, None))


def render_to_rgb8(vv_db: np.ndarray, db_window: tuple[float, float]) -> np.ndarray:
    """Clips to the configured dB window, stretches to 0-255 uint8, and
    replicates to 3 channels so the model sees what it was trained on."""
    lo, hi = db_window
    if hi <= lo:
        raise ValueError(f"db_window must have hi > lo, got {db_window}")
    clipped = np.clip(vv_db, lo, hi)
    stretched = (clipped - lo) / (hi - lo) * 255.0
    gray = stretched.astype(np.uint8)
    return np.repeat(gray[:, :, None], 3, axis=2)


def render_geotiff(path: str, db_window: tuple[float, float]) -> tuple[np.ndarray, Affine, str]:
    """End to end: read the VV band, convert to dB, render to RGB8.
    Returns (image_rgb8, transform, crs)."""
    sigma0, transform, crs = read_vv_band(path)
    db = sigma0_to_db(sigma0)
    rgb8 = render_to_rgb8(db, db_window)
    return rgb8, transform, crs
