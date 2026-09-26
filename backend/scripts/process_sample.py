"""Runs detection over the staged sample SAR image and prints what it found.

The smallest useful thing Pharos can be asked to do, and the fastest way
to confirm an install works. It needs no dataset download, no database,
no Docker and no frontend: the sample scene is committed to the
repository (data/fixtures/SAMPLE_SCENE.md explains what it is), so a
fresh clone can process an image immediately.

    python scripts/process_sample.py

That runs the real P2 path from PLAN.md section 5, render -> tile ->
infer -> stitch -> polygonize, and writes the oil polygons to
data/processed/sample_detections.geojson in EPSG:4326.

Point it at your own calibrated-sigma0 GeoTIFF with --scene. Band 1 is
read as VV and is expected to be linear power, not dB and not raw DN;
services/detection/render.py is the one place that conversion happens.

For the whole pipeline rather than just detection (wind gate, backward
drift, AIS reconstruction, scoring, verdict, dossier) use
scripts/seed_demo.py instead. This script deliberately stops at
detection so it stays fast enough to be a smoke test.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

DEFAULT_SCENE = "data/fixtures/synthetic_scene.tif"
DEFAULT_OUT = "data/processed/sample_detections.geojson"
DEFAULT_SCENE_ID = "PHAROS-SAMPLE-0001"


def _area_km2(geometry: dict, lat_hint: float) -> float:
    """Rough planar area of a lon/lat polygon, for display only. Nothing
    downstream reads this: the scoring engine works from the projected
    geometry, not from a printed number."""
    import math

    from shapely.geometry import shape

    deg_km = 111.32
    return shape(geometry).area * deg_km * deg_km * math.cos(math.radians(lat_hint))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Process one SAR scene through Pharos's detection stage.",
    )
    parser.add_argument("--scene", default=DEFAULT_SCENE, help=f"GeoTIFF to process (default: {DEFAULT_SCENE})")
    parser.add_argument("--scene-id", default=DEFAULT_SCENE_ID, help="scene id stamped onto every detection")
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"GeoJSON output path (default: {DEFAULT_OUT})")
    args = parser.parse_args(argv)

    os.chdir(BACKEND_DIR)

    if not os.path.exists(args.scene):
        print(f"scene not found: {args.scene}", file=sys.stderr)
        print("The staged sample ships with the repository. If it is missing, rebuild it with:", file=sys.stderr)
        print("    python scripts/make_synthetic_data.py --only scene --force", file=sys.stderr)
        return 1

    from services.detection.app import load_config, run_pipeline

    config = load_config()
    print(f"scene:    {args.scene}")
    print(f"model:    {config['detection']['model_local_dir']}/model.keras")
    print(f"classes:  {', '.join(config['detection']['classes'])}")
    print("running render -> tile -> infer -> stitch -> polygonize ...")

    feature_collection = run_pipeline(args.scene, args.scene_id, config)
    features = feature_collection["features"]

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(feature_collection, f)

    print()
    if not features:
        print("no oil detections above the minimum area threshold")
        print(f"threshold: {config['detection']['polygonize']['min_area_km2']} km2")
        print(f"wrote an empty FeatureCollection to {args.out}")
        return 0

    print(f"{len(features)} oil detection(s):")
    print(f"  {'detection_id':<26} {'mean prob':>9} {'pixels':>8} {'area km2':>9}  centroid (lon, lat)")
    for feature in features:
        props = feature["properties"]
        from shapely.geometry import shape

        centroid = shape(feature["geometry"]).centroid
        area = _area_km2(feature["geometry"], centroid.y)
        print(
            f"  {props['detection_id']:<26} {props['mean_class_prob']:>9.3f} "
            f"{props['pixel_area']:>8} {area:>9.3f}  ({centroid.x:.4f}, {centroid.y:.4f})"
        )

    print()
    print(f"wrote {args.out}")
    print("Next: scripts/seed_demo.py runs the full pipeline (drift, AIS, scoring, verdict, dossier).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
