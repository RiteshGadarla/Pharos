"""FastAPI service and pipeline orchestration for detection.
See PLAN.md section 5: render -> tile -> infer -> stitch -> polygonize.
"""

from __future__ import annotations

from functools import lru_cache

import yaml
from fastapi import FastAPI

from services.detection.infer import load_model, run_inference
from services.detection.polygonize import detect_oil
from services.detection.render import render_geotiff

app = FastAPI(title="drishta-detection")

CONFIG_PATH = "config/pipeline.yaml"


def load_config(path: str = CONFIG_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def get_model(model_path: str):
    return load_model(model_path)


def run_pipeline(geotiff_path: str, scene_id: str, config: dict) -> dict:
    """End to end: render -> tile -> infer -> stitch -> polygonize.
    Returns a GeoJSON FeatureCollection of oil detections, coordinates in
    EPSG:4326. This is the function PLAN.md section 14's P2 acceptance
    test exercises: given a GeoTIFF, correct-geography oil polygons out.
    """
    det_cfg = config["detection"]

    image_rgb8, transform, crs = render_geotiff(geotiff_path, tuple(det_cfg["render"]["db_window"]))

    model_path = f"{det_cfg['model_local_dir']}/model.keras"
    model = get_model(model_path)

    softmax = run_inference(
        model,
        image_rgb8,
        tile_size=det_cfg["tiling"]["tile_size"],
        overlap=det_cfg["tiling"]["overlap_px"],
        n_classes=len(det_cfg["classes"]),
        land_skip_fraction=det_cfg["tiling"]["land_skip_fraction"],
    )

    return detect_oil(
        softmax,
        transform,
        crs,
        classes=det_cfg["classes"],
        min_area_km2=det_cfg["polygonize"]["min_area_km2"],
        scene_id=scene_id,
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "detection"}


@app.post("/detect")
def detect(scene_id: str, geotiff_path: str) -> dict:
    config = load_config()
    return run_pipeline(geotiff_path, scene_id, config)
