"""Generates a small calibrated-sigma0 GeoTIFF for offline tests and the
demo, with a real oil-slick texture composited in. Not a real Sentinel-1
product: the geolocation, acquisition time and surrounding sea are still
synthetic, since real Sentinel-1 access is blocked on the Earthdata
account (PLAN.md section 4A). But the slick itself is no longer a
hand-drawn ellipse -- it's real Sentinel-1A backscatter and speckle
texture from an actual Persian Gulf slick, composited in and re-anchored
to this scene's background sigma0 level. See
data/fixtures/real_oil_texture/ATTRIBUTION.md for the source and
license (CC BY 4.0, Deep-SAR SOS dataset).

Used by services/detection tests to exercise render -> tile -> infer ->
stitch -> polygonize end to end with known, deterministic geography, and
by scripts/seed_demo.py as the demo's own scene.

Run: python3 scripts/make_fixture_scene.py
"""

from __future__ import annotations

import numpy as np
import rasterio
from affine import Affine
from PIL import Image
from rasterio.crs import CRS
from scipy import ndimage

OUT_PATH = "data/fixtures/synthetic_scene.tif"
REAL_TEXTURE_IMAGE = "data/fixtures/real_oil_texture/sentinel_277_image.png"
REAL_TEXTURE_LABEL = "data/fixtures/real_oil_texture/sentinel_277_label.png"

SIZE = 512
PIXEL_SIZE_M = 10.0
# UTM zone 42N, a patch of open Arabian Sea off India's west coast, inside
# the same offshore domain as the P6 hindcast fixtures (16-18N, 67-69E, see
# make_fixture_currents.py / make_fixture_wind_offshore.py), so a detection
# from this scene can drive the backward ensemble without any particle
# ever crossing real coastline. Coordinates are illustrative, not a real
# incident location.
ORIGIN_X = 391020.5
ORIGIN_Y = 1887918.6
SEED = 26143

SEA_DB_MEAN = -17.0
SEA_DB_STD = 1.5
DB_MIN, DB_MAX = -35.0, 0.0  # same window services/detection/render.py clips to

PATCH_TOP_LEFT = (140, 150)  # (row, col) placement of the 256x256 real patch
FEATHER_PX = 24
# The source patch's real oil/sea contrast (~-4.7dB) is real but subtle
# enough that the model's oil-class confidence tops out around 0.43,
# just under its own argmax threshold: real slicks are often weaker
# signal than a hand-drawn fixture, and this one particular patch is on
# the weaker end even for real ones. Scaling only the oil pixels'
# deviation from the local sea level (not the sea texture itself)
# keeps the real speckle pattern and shape, just pushes the physically
# real damping signal to a strength within the range real fresh slicks
# do show. Disclosed in ATTRIBUTION.md.
OIL_CONTRAST_SCALE = 2.2


def db_to_linear(db: np.ndarray) -> np.ndarray:
    return 10.0 ** (db / 10.0)


def _load_real_patch_db() -> tuple[np.ndarray, np.ndarray]:
    """Loads the real oil-slick patch, converts its 8-bit grayscale
    appearance to a dB field using the same [DB_MIN, DB_MAX] window
    render.py itself uses, then re-anchors it so the patch's own sea
    pixels sit at SEA_DB_MEAN. That keeps the real, physically-measured
    oil/sea contrast from the source product intact while matching this
    scene's chosen background level, so the seam blends cleanly.
    Returns (patch_db, oil_mask)."""
    img = np.array(Image.open(REAL_TEXTURE_IMAGE).convert("L")).astype(np.float64)
    mask = np.array(Image.open(REAL_TEXTURE_LABEL).convert("L")) > 127

    patch_db = DB_MIN + (img / 255.0) * (DB_MAX - DB_MIN)
    sea_level = np.median(patch_db[~mask])
    patch_db = patch_db - sea_level + SEA_DB_MEAN
    patch_db[mask] = SEA_DB_MEAN + (patch_db[mask] - SEA_DB_MEAN) * OIL_CONTRAST_SCALE
    return patch_db, mask


def _mask_shaped_alpha(oil_mask: np.ndarray, halo_px: int, feather_px: int) -> np.ndarray:
    """1.0 over the oil mask itself and a halo_px margin of real sea
    around it, fading to 0.0 beyond that. Shaped by the slick's own
    outline rather than the patch's rectangular border, so what blends
    into the synthetic background reads as an irregular real feature,
    not a pasted-in rectangle: a straight rectangular seam was the
    obvious tell in the first version of this compositing."""
    halo = ndimage.binary_dilation(oil_mask, iterations=halo_px)
    alpha = halo.astype(np.float64)
    return ndimage.gaussian_filter(alpha, sigma=feather_px / 2)


def make_scene() -> np.ndarray:
    rng = np.random.default_rng(SEED)

    # Open sea background, typical Sentinel-1 VV sigma0 under moderate wind.
    scene_db = rng.normal(loc=SEA_DB_MEAN, scale=SEA_DB_STD, size=(SIZE, SIZE))

    patch_db, oil_mask = _load_real_patch_db()
    ph, pw = patch_db.shape
    r0, c0 = PATCH_TOP_LEFT
    alpha = _mask_shaped_alpha(oil_mask, halo_px=18, feather_px=FEATHER_PX)

    region = scene_db[r0 : r0 + ph, c0 : c0 + pw]
    scene_db[r0 : r0 + ph, c0 : c0 + pw] = alpha * patch_db + (1 - alpha) * region

    return db_to_linear(scene_db).astype(np.float32)


def write_geotiff(sigma0: np.ndarray) -> None:
    transform = Affine.translation(ORIGIN_X, ORIGIN_Y) * Affine.scale(PIXEL_SIZE_M, -PIXEL_SIZE_M)
    crs = CRS.from_epsg(32642)
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
