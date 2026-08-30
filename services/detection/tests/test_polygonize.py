import numpy as np
import pytest
from affine import Affine

from services.detection.polygonize import (
    MODEL_TO_SCHEMA_CLASS,
    detect_oil,
    polygonize_class,
    to_feature_collection,
)

CLASSES = ["background", "oil_spill", "ships", "look_alike", "wakes"]
# 10 m pixels, a UTM-43N-ish origin, north up.
TRANSFORM = Affine(10.0, 0.0, 500000.0, 0.0, -10.0, 2200000.0)
SRC_CRS = "EPSG:32643"


def make_softmax_with_blob(shape=(20, 20), blob=(4, 4, 10, 8), oil_prob=0.9) -> np.ndarray:
    """blob = (row0, col0, height, width) of a rectangular oil_spill region."""
    softmax = np.zeros((*shape, len(CLASSES)), dtype=np.float32)
    softmax[..., 0] = 1.0  # everything background by default
    r0, c0, h, w = blob
    softmax[r0 : r0 + h, c0 : c0 + w, 0] = 1.0 - oil_prob
    softmax[r0 : r0 + h, c0 : c0 + w, 1] = oil_prob
    return softmax


def test_polygonize_class_finds_the_blob_with_correct_area_and_prob():
    softmax = make_softmax_with_blob()
    detections = polygonize_class(
        softmax,
        TRANSFORM,
        SRC_CRS,
        class_index=1,
        class_name="oil",
        min_area_km2=0.0,
    )
    assert len(detections) == 1
    det = detections[0]
    assert det["class_name"] == "oil"
    assert det["pixel_area"] == 10 * 8  # height * width from the blob
    expected_area_km2 = (10 * 10) * (8 * 10) / 1e6  # metres, then to km2
    assert det["area_km2"] == pytest.approx(expected_area_km2, rel=1e-6)
    assert det["mean_class_prob"] == pytest.approx(0.9, abs=1e-5)
    assert det["geometry"]["type"] == "Polygon"


def test_polygonize_class_reprojects_to_epsg4326_with_plausible_coordinates():
    softmax = make_softmax_with_blob()
    detections = polygonize_class(softmax, TRANSFORM, SRC_CRS, 1, "oil", min_area_km2=0.0)
    coords = detections[0]["geometry"]["coordinates"][0]
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    # UTM 43N covers roughly 72-78 E; sanity check we landed in a plausible band,
    # not e.g. still in metres or on the wrong side of the globe.
    assert all(60 < lon < 90 for lon in lons)
    assert all(0 < lat < 40 for lat in lats)


def test_polygonize_class_min_area_filters_out_small_blobs():
    softmax = make_softmax_with_blob()
    detections = polygonize_class(softmax, TRANSFORM, SRC_CRS, 1, "oil", min_area_km2=1.0)
    assert detections == []


def test_polygonize_class_returns_empty_when_class_absent():
    softmax = np.zeros((10, 10, len(CLASSES)), dtype=np.float32)
    softmax[..., 0] = 1.0
    detections = polygonize_class(softmax, TRANSFORM, SRC_CRS, 1, "oil", min_area_km2=0.0)
    assert detections == []


def test_to_feature_collection_wraps_detections_with_stable_ids():
    softmax = make_softmax_with_blob()
    detections = polygonize_class(softmax, TRANSFORM, SRC_CRS, 1, "oil", min_area_km2=0.0)
    fc = to_feature_collection(detections, scene_id="SCENE-1")
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 1
    props = fc["features"][0]["properties"]
    assert props["detection_id"] == "SCENE-1-oil-000"
    assert props["scene_id"] == "SCENE-1"
    assert props["class_name"] == "oil"


def test_detect_oil_maps_model_class_name_to_schema_class_name():
    assert MODEL_TO_SCHEMA_CLASS["oil_spill"] == "oil"
    softmax = make_softmax_with_blob()
    fc = detect_oil(softmax, TRANSFORM, SRC_CRS, CLASSES, min_area_km2=0.0, scene_id="SCENE-1")
    assert len(fc["features"]) == 1
    assert fc["features"][0]["properties"]["class_name"] == "oil"
