"""End to end P2 acceptance test, PLAN.md section 14:
"Given a GeoTIFF, returns a GeoJSON FeatureCollection of oil polygons
with correct geographic coordinates."

Uses the real downloaded model and the synthetic fixture GeoTIFF
(scripts/make_fixture_scene.py), since a real Sentinel-1 scene is not
yet available (PLAN.md section 4A, blocked on the Earthdata account).
Skipped if the model has not been downloaded, since data/models/ is
gitignored and this is a large fetched artifact, not source.
"""

import os

import pytest
import rasterio
from rasterio.warp import transform_bounds

from services.detection.app import load_config, run_pipeline

MODEL_PATH = "data/models/oil-spill-deeplab/model.keras"
FIXTURE_PATH = "data/fixtures/synthetic_scene.tif"

requires_model = pytest.mark.skipif(
    not os.path.exists(MODEL_PATH),
    reason="model not downloaded, see PLAN.md section 4A: huggingface_hub.hf_hub_download('sahilvishwa2108/oil-spill-deeplab', 'model.keras')",
)


@requires_model
def test_pipeline_returns_feature_collection_with_correct_geography():
    config = load_config("config/pipeline.yaml")
    result = run_pipeline(FIXTURE_PATH, "FIXTURE-001", config)

    assert result["type"] == "FeatureCollection"
    assert isinstance(result["features"], list)

    with rasterio.open(FIXTURE_PATH) as ds:
        scene_bounds_4326 = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
    min_lon, min_lat, max_lon, max_lat = scene_bounds_4326

    for feature in result["features"]:
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] == "Polygon"
        assert feature["properties"]["class_name"] == "oil"
        assert feature["properties"]["scene_id"] == "FIXTURE-001"
        assert 0.0 <= feature["properties"]["mean_class_prob"] <= 1.0

        coords = feature["geometry"]["coordinates"][0]
        for lon, lat in coords:
            # detected polygons must fall within the source scene's own
            # footprint, this is the "correct geographic coordinates" check
            assert min_lon <= lon <= max_lon
            assert min_lat <= lat <= max_lat


@requires_model
def test_pipeline_detects_the_embedded_synthetic_slick():
    config = load_config("config/pipeline.yaml")
    result = run_pipeline(FIXTURE_PATH, "FIXTURE-001", config)
    # The fixture embeds a distinct low-backscatter elongated region
    # (PLAN.md's "fresh" profile). The real model should find something,
    # even if it doesn't always recover it as one single polygon.
    assert len(result["features"]) >= 1
