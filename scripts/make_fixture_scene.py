"""Generates a small synthetic calibrated-sigma0 GeoTIFF for offline tests.

Not a real Sentinel-1 product. Stands in for one until a real scene is
available (PLAN.md section 4A, blocked on the Earthdata account). Used by
services/detection tests to exercise render -> tile -> infer -> stitch
-> polygonize end to end with known, deterministic geography.

Run: python3 scripts/make_fixture_scene.py
"""

from __future__ import annotations

import numpy as np
import rasterio
from affine import Affine
from rasterio.crs import CRS

OUT_PATH = "data/fixtures/synthetic_scene.tif"
SIZE = 512
PIXEL_SIZE_M = 10.0
# UTM zone 43N, a patch of the Arabian Sea off India's west coast.
# Coordinates are illustrative, not a real incident location.
ORIGIN_X = 260000.0
ORIGIN_Y = 2150000.0
SEED = 26143


def db_to_linear(db: np.ndarray) -> np.ndarray:
    return 10.0 ** (db / 10.0)


def make_scene() -> np.ndarray:
    rng = np.random.default_rng(SEED)

    # Open sea background, typical Sentinel-1 VV sigma0 under moderate wind.
    sea_db = rng.normal(loc=-17.0, scale=1.5, size=(SIZE, SIZE))

    # An elongated slick, angled, low backscatter, roughly PLAN.md's
    # "fresh" profile: high contrast, compact-ish.
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    cx, cy = SIZE * 0.45, SIZE * 0.55
    angle = np.deg2rad(35.0)
    major, minor = 140.0, 40.0
    xr = (xx - cx) * np.cos(angle) + (yy - cy) * np.sin(angle)
    yr = -(xx - cx) * np.sin(angle) + (yy - cy) * np.cos(angle)
    slick_mask = (xr / major) ** 2 + (yr / minor) ** 2 <= 1.0

    slick_db = rng.normal(loc=-28.0, scale=1.0, size=(SIZE, SIZE))

    scene_db = np.where(slick_mask, slick_db, sea_db)
    return db_to_linear(scene_db).astype(np.float32)


def write_geotiff(sigma0: np.ndarray) -> None:
    transform = Affine.translation(ORIGIN_X, ORIGIN_Y) * Affine.scale(PIXEL_SIZE_M, -PIXEL_SIZE_M)
    crs = CRS.from_epsg(32643)
    with rasterio.open(
        OUT_PATH,
        "w",
        driver="GTiff",
        height=sigma0.shape[0],
        width=sigma0.shape[1],
        count=1,
        dtype=sigma0.dtype,
        crs=crs,
        transform=transform,
        compress="deflate",
    ) as dst:
        dst.write(sigma0, 1)


if __name__ == "__main__":
    sigma0 = make_scene()
    write_geotiff(sigma0)
    print(f"wrote {OUT_PATH}, shape={sigma0.shape}, dtype={sigma0.dtype}")
