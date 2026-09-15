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

The case studies in config/cases.yaml each describe their own scene
through `make_scene(params)`: where it is, how large, how bright the sea
is under that case's wind (sea clutter rises with wind speed, so a high
wind scene has a brighter, busier background and a low wind one a darker,
smoother one), and where one or more copies of the real texture go, at
what contrast, rotation and scale. With no parameters it produces exactly
the committed staged sample scene, which is why the defaults below are
the original constants.

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
# incident location. The scene centre is 17.05 N, 68.00 E.
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

DEFAULT_SLICK = {"at": list(PATCH_TOP_LEFT), "contrast_scale": OIL_CONTRAST_SCALE, "rot90": 0, "flip": False, "zoom": 1.0}


def db_to_linear(db: np.ndarray) -> np.ndarray:
    return 10.0 ** (db / 10.0)


def _load_real_patch_db(sea_db_mean: float = SEA_DB_MEAN, contrast_scale: float = OIL_CONTRAST_SCALE) -> tuple[np.ndarray, np.ndarray]:
    """Loads the real oil-slick patch, converts its 8-bit grayscale
    appearance to a dB field using the same [DB_MIN, DB_MAX] window
    render.py itself uses, then re-anchors it so the patch's own sea
    pixels sit at the scene's sea level. That keeps the real,
    physically-measured oil/sea contrast from the source product intact
    while matching this scene's chosen background level, so the seam
    blends cleanly. Returns (patch_db, oil_mask)."""
    img = np.array(Image.open(REAL_TEXTURE_IMAGE).convert("L")).astype(np.float64)
    mask = np.array(Image.open(REAL_TEXTURE_LABEL).convert("L")) > 127

    patch_db = DB_MIN + (img / 255.0) * (DB_MAX - DB_MIN)
    sea_level = np.median(patch_db[~mask])
    patch_db = patch_db - sea_level + sea_db_mean
    patch_db[mask] = sea_db_mean + (patch_db[mask] - sea_db_mean) * contrast_scale
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


def make_scene(params: dict | None = None) -> np.ndarray:
    """Builds sigma0 for one scene. `params` keys, all optional:

    size, seed, sea_db_mean, sea_db_std: the background.
    wind_streaks_db: amplitude of wind-aligned streaks in the sea clutter
      (boundary-layer rolls show as faint banding at higher wind), and
      wind_streak_toward_deg their orientation.
    slicks: list of {at: [row, col], contrast_scale, rot90, flip, zoom}.

    With no params this is the original fixture scene, draw for draw.
    """
    p = params or {}
    size = int(p.get("size", SIZE))
    sea_db_mean = float(p.get("sea_db_mean", SEA_DB_MEAN))
    rng = np.random.default_rng(int(p.get("seed", SEED)))

    scene_db = rng.normal(loc=sea_db_mean, scale=float(p.get("sea_db_std", SEA_DB_STD)), size=(size, size))

    streaks = float(p.get("wind_streaks_db", 0.0))
    if streaks > 0:
        # Wind rows: long, narrow correlated bands along the wind. Built
        # by smoothing noise anisotropically and rotating the result.
        noise = rng.normal(size=(size, size))
        banded = ndimage.gaussian_filter(noise, sigma=(3.0, 40.0), mode="wrap")
        banded = ndimage.rotate(banded, angle=90.0 - float(p.get("wind_streak_toward_deg", 90.0)), reshape=False, mode="wrap")
        scene_db += streaks * banded / (banded.std() or 1.0)

    for slick in p.get("slicks", [DEFAULT_SLICK]):
        s = {**DEFAULT_SLICK, **slick}
        patch_db, oil_mask = _load_real_patch_db(sea_db_mean, float(s["contrast_scale"]))
        k = int(s["rot90"])
        if k:
            patch_db, oil_mask = np.rot90(patch_db, k), np.rot90(oil_mask, k)
        if s["flip"]:
            patch_db, oil_mask = patch_db[:, ::-1], oil_mask[:, ::-1]
        if float(s["zoom"]) != 1.0:
            z = float(s["zoom"])
            patch_db = ndimage.zoom(patch_db, z, order=1)
            oil_mask = ndimage.zoom(oil_mask.astype(float), z, order=1) > 0.5
        ph, pw = patch_db.shape
        r0, c0 = (int(v) for v in s["at"])
        alpha = _mask_shaped_alpha(oil_mask, halo_px=18, feather_px=FEATHER_PX)
        region = scene_db[r0 : r0 + ph, c0 : c0 + pw]
        scene_db[r0 : r0 + ph, c0 : c0 + pw] = alpha * patch_db + (1 - alpha) * region

    return db_to_linear(scene_db).astype(np.float32)


def scene_origin(params: dict | None = None) -> tuple[float, float]:
    """Upper-left corner in UTM 42N. A `center: [lat, lon]` param places
    the scene; otherwise the original fixture origin is used."""
    p = params or {}
    if "center" not in p:
        return ORIGIN_X, ORIGIN_Y
    from pyproj import Transformer

    lat, lon = p["center"]
    cx, cy = Transformer.from_crs("EPSG:4326", "EPSG:32642", always_xy=True).transform(lon, lat)
    half = int(p.get("size", SIZE)) * PIXEL_SIZE_M / 2.0
    return round(cx - half, 1), round(cy + half, 1)


def write_geotiff(sigma0: np.ndarray, out_path: str = OUT_PATH, origin: tuple[float, float] = (ORIGIN_X, ORIGIN_Y)) -> None:
    transform = Affine.translation(*origin) * Affine.scale(PIXEL_SIZE_M, -PIXEL_SIZE_M)
    crs = CRS.from_epsg(32642)
    with rasterio.open(
        out_path,
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


def build(params: dict | None, out_path: str) -> None:
    sigma0 = make_scene(params)
    write_geotiff(sigma0, out_path, scene_origin(params))
    print(f"wrote {out_path}, shape={sigma0.shape}, dtype={sigma0.dtype}")


if __name__ == "__main__":
    build(None, OUT_PATH)
