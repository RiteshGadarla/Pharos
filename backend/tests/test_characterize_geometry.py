import math

import numpy as np
import pytest
import rasterio
import rasterio.features
from affine import Affine
from rasterio.crs import CRS
from rasterio.warp import transform_geom
from shapely.geometry import mapping, shape

from services.core.characterize.geometry import compute_slick_features_dict
from services.core.schemas import Detection

SRC_CRS = CRS.from_epsg(32643)
PIXEL_SIZE_M = 10.0
BACKGROUND_DB = -15.0
SLICK_DB = -25.0
# axis-aligned rectangle: 40 px wide (400 m), 10 px tall (100 m)
RECT = dict(row0=40, col0=20, height=10, width=40)


def _db_to_linear(db: float) -> float:
    return 10.0 ** (db / 10.0)


@pytest.fixture
def rectangle_fixture(tmp_path):
    size = 100
    sigma0 = np.full((size, size), _db_to_linear(BACKGROUND_DB), dtype=np.float32)
    r0, c0, h, w = RECT["row0"], RECT["col0"], RECT["height"], RECT["width"]
    sigma0[r0 : r0 + h, c0 : c0 + w] = _db_to_linear(SLICK_DB)

    transform = Affine.translation(500000.0, 2200000.0) * Affine.scale(PIXEL_SIZE_M, -PIXEL_SIZE_M)
    tif_path = tmp_path / "rectangle.tif"
    with rasterio.open(
        tif_path, "w", driver="GTiff", height=size, width=size, count=1,
        dtype=sigma0.dtype, crs=SRC_CRS, transform=transform,
    ) as dst:
        dst.write(sigma0, 1)

    mask = np.zeros((size, size), dtype=np.uint8)
    mask[r0 : r0 + h, c0 : c0 + w] = 1
    shapes_gen = rasterio.features.shapes(mask, mask=mask.astype(bool), transform=transform)
    geom_src, _ = next(shapes_gen)
    geom_4326 = transform_geom(SRC_CRS, "EPSG:4326", geom_src)

    detection = Detection(
        detection_id="det-rect",
        scene_id="SCENE-1",
        class_name="oil",
        geometry=geom_4326,
        mean_class_prob=0.9,
        pixel_area=h * w,
    )
    return detection, str(tif_path)


def test_area_and_perimeter_match_the_known_rectangle(rectangle_fixture):
    detection, tif_path = rectangle_fixture
    features = compute_slick_features_dict(detection, tif_path)

    expected_area_km2 = (RECT["height"] * PIXEL_SIZE_M) * (RECT["width"] * PIXEL_SIZE_M) / 1e6
    expected_perimeter_km = 2 * ((RECT["height"] * PIXEL_SIZE_M) + (RECT["width"] * PIXEL_SIZE_M)) / 1000

    assert features["area_km2"] == pytest.approx(expected_area_km2, rel=0.02)
    assert features["perimeter_km"] == pytest.approx(expected_perimeter_km, rel=0.02)


def test_complexity_ratio_formula(rectangle_fixture):
    detection, tif_path = rectangle_fixture
    features = compute_slick_features_dict(detection, tif_path)
    expected = features["perimeter_km"] / (2 * math.sqrt(math.pi * features["area_km2"]))
    assert features["complexity_ratio"] == pytest.approx(expected, rel=1e-9)
    # a 4:1 rectangle is not a circle, complexity_ratio must be > 1
    assert features["complexity_ratio"] > 1.0


def test_major_axis_is_horizontal_for_a_wide_rectangle(rectangle_fixture):
    detection, tif_path = rectangle_fixture
    features = compute_slick_features_dict(detection, tif_path)
    angle = features["major_axis_deg"]
    # horizontal is 0 or 180 (mod 180 wraparound), allow reprojection noise
    assert min(angle, 180 - angle) < 2.0


def test_elongation_matches_the_known_aspect_ratio(rectangle_fixture):
    detection, tif_path = rectangle_fixture
    features = compute_slick_features_dict(detection, tif_path)
    expected = RECT["width"] / RECT["height"]  # 40/10 = 4.0
    assert features["elongation"] == pytest.approx(expected, rel=0.05)


def test_backscatter_and_contrast_match_known_db_values(rectangle_fixture):
    detection, tif_path = rectangle_fixture
    features = compute_slick_features_dict(detection, tif_path)
    assert features["mean_backscatter_db"] == pytest.approx(SLICK_DB, abs=0.5)
    expected_contrast = SLICK_DB - BACKGROUND_DB
    assert features["contrast_db"] == pytest.approx(expected_contrast, abs=0.5)
