"""Produces the precomputed demo bundle in data/precomputed/. See PLAN.md section 15.

Runs the real pipeline once, offline, on the committed fixtures (no real
Sentinel-1 scene yet, PLAN.md section 4A item 4; no real AIS, section 9):

  detection (render/tile/infer/polygonize) -> wind gate -> characterise
  -> backward drift ensemble -> origin probability field -> synthetic AIS
  scenario -> elimination -> scoring

and writes one self-contained JSON bundle, data/precomputed/demo_bundle.json,
that the frontend loads with no live pipeline calls and no database. This
is what DEMO_MODE=offline serves (PLAN.md section 15).

Run from backend/: .venv/bin/python scripts/seed_demo.py
"""

from __future__ import annotations

import datetime
import json

import xarray as xr
import yaml
from rasterio.warp import transform_bounds
import rasterio

from services.core.ais.synthetic import generate_demo_scenario
from services.core.characterize.age import with_age
from services.core.characterize.geometry import compute_slick_features_dict
from services.core.dossier.render import render_dossier
from services.core.gate.wind import gate_detections, load_wind_field
from services.core.hindcast.ensemble import run_ensemble
from services.core.hindcast.field import build_origin_field
from services.core.preview import render_scene_preview
from services.core.schemas import Detection
from services.core.scoring.eliminate import eliminate_and_survive
from services.core.scoring.engine import score_vessels
from services.detection.app import load_config as load_pipeline_config
from services.detection.app import run_pipeline

SCENE_PATH = "data/fixtures/synthetic_scene.tif"
CURRENTS_PATH = "data/fixtures/synthetic_currents.nc"
WIND_PATH = "data/fixtures/synthetic_wind_offshore.nc"
OUT_PATH = "data/precomputed/demo_bundle.json"
DOSSIER_OUT_PATH = "data/precomputed/case_dossier.pdf"
SCENE_PREVIEW_OUT_PATH = "data/precomputed/scene_preview.png"

SCENE_ID = "SLICKTRACE-DEMO-0001"
ACQUIRED_AT = datetime.datetime(2026, 1, 15, 2, 30)

# Hindcast run kept small deliberately: this is a demo precompute, not the
# full 30-member run (that's what the "reduced live" hindcast button in the
# UI is for, PLAN.md section 15). Same shape as
# scripts/make_fixture_origin_field.py so the field stays a similar size.
HINDCAST_OVERRIDES = {
    "n_members_full": 8,
    "particles_per_member": 30,
    "backward_horizon_hours": 6,
    "wind_drift_factor_range": [0.02, 0.04],
    "current_perturbation_magnitude": 0.05,
    "horizontal_diffusivity_range": [1.0, 10.0],
    "seed_time_jitter_minutes": 15,
    "field": {
        "grid_resolution_deg": 0.01,
        "time_step_minutes": 20,
        "gaussian_bandwidth_deg": 0.02,
    },
}

AIS_CONFIG = {"dark_gap_min_minutes": 20, "max_plausible_speed_kn": 30}


def _iso(ts) -> str:
    if isinstance(ts, datetime.datetime):
        return ts.isoformat()
    return str(ts)


def _to_pydatetime(value) -> datetime.datetime:
    import pandas as pd

    return pd.Timestamp(value).to_pydatetime()


def load_scoring_config() -> dict:
    with open("config/scoring.yaml") as f:
        return yaml.safe_load(f)


def build_scene_meta(scene_path: str, scene_id: str, acquired_at: datetime.datetime) -> dict:
    with rasterio.open(scene_path) as ds:
        bbox = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
        crs = ds.crs.to_string()
    return {
        "scene_id": scene_id,
        "acquired_at": _iso(acquired_at),
        "bbox": list(bbox),
        "crs": crs,
        "source_path": scene_path,
        "note": (
            "Synthetic fixture scene, not a real Sentinel-1 product (PLAN.md section 4A). "
            "The slick's texture is real Sentinel-1A oil-spill backscatter and speckle, "
            "composited in from a different real location (Persian Gulf, CC BY 4.0 Deep-SAR "
            "SOS dataset); the scene's geolocation, acquisition time and surrounding sea are "
            "synthetic. See data/fixtures/real_oil_texture/ATTRIBUTION.md."
        ),
    }


def run_detection(pipeline_config: dict, scene_path: str, scene_id: str) -> list[Detection]:
    feature_collection = run_pipeline(scene_path, scene_id, pipeline_config)
    detections = []
    for feature in feature_collection["features"]:
        props = feature["properties"]
        detections.append(
            Detection(
                detection_id=props["detection_id"],
                scene_id=props["scene_id"],
                class_name=props["class_name"],
                geometry=feature["geometry"],
                mean_class_prob=props["mean_class_prob"],
                pixel_area=props["pixel_area"],
            )
        )
    return detections


def build_hindcast_config(pipeline_config: dict) -> dict:
    hindcast_cfg = dict(pipeline_config["hindcast"])
    hindcast_cfg.update({k: v for k, v in HINDCAST_OVERRIDES.items() if k != "field"})
    hindcast_cfg["field"] = {**hindcast_cfg.get("field", {}), **HINDCAST_OVERRIDES["field"]}
    return {"seed": pipeline_config["seed"], "hindcast": hindcast_cfg}


def origin_field_to_json(field_ds: xr.Dataset) -> dict:
    times = [pd_ts for pd_ts in field_ds["time"].values]
    return {
        "seed": int(field_ds.attrs["seed"]),
        "n_members": int(field_ds.attrs["n_members"]),
        "t_min": _iso(_to_pydatetime(times[0])),
        "t_max": _iso(_to_pydatetime(times[-1])),
        "time": [_iso(_to_pydatetime(t)) for t in times],
        "lat": [float(v) for v in field_ds["lat"].values],
        "lon": [float(v) for v in field_ds["lon"].values],
        # dims (time, lat, lon), sums to 1 over the whole volume, PLAN.md non-negotiable 1
        "grid": field_ds["probability"].values.tolist(),
    }


def ais_point_to_json(point) -> dict:
    return {
        "ts": _iso(point.ts),
        "lat": point.lat,
        "lon": point.lon,
        "sog": point.sog,
        "cog": point.cog,
        "heading": point.heading,
    }


def dark_gap_to_json(gap) -> dict:
    return {
        "start": _iso(gap.start),
        "end": _iso(gap.end),
        "duration_min": gap.duration_min,
        "entry_point": list(gap.entry_point),
        "exit_point": list(gap.exit_point),
        "envelope": gap.envelope,
    }


def main() -> None:
    pipeline_config = load_pipeline_config("config/pipeline.yaml")
    scoring_config = load_scoring_config()
    with open("config/demo.yaml") as f:
        demo_config = yaml.safe_load(f)
    incident_context = demo_config["incident"]

    print("Running detection on the fixture scene...")
    detections = run_detection(pipeline_config, SCENE_PATH, SCENE_ID)
    oil_detections = [d for d in detections if d.class_name == "oil"]
    if not oil_detections:
        raise SystemExit("no oil detections on the fixture scene, cannot seed the demo")
    primary = max(oil_detections, key=lambda d: d.pixel_area)
    print(f"  {len(detections)} detection(s), primary oil polygon {primary.detection_id} ({primary.pixel_area} px)")

    print("Rendering the scene basemap PNG...")
    scene_preview = render_scene_preview(SCENE_PATH, SCENE_PREVIEW_OUT_PATH)
    print(f"  {scene_preview['width']}x{scene_preview['height']} px, {SCENE_PREVIEW_OUT_PATH}")

    print("Applying the wind gate...")
    wind_ds = load_wind_field(WIND_PATH)
    gate_results = gate_detections(oil_detections, wind_ds, ACQUIRED_AT, pipeline_config["wind_gate"])
    gate_by_id = {g.detection_id: g for g in gate_results}
    print(f"  primary verdict: {gate_by_id[primary.detection_id].verdict}")

    print("Characterising the primary slick...")
    features_dict = compute_slick_features_dict(primary, SCENE_PATH)
    slick_features = with_age(features_dict)
    print(f"  age band: {slick_features.age_band}")

    print("Running the backward drift ensemble (this is the slow step)...")
    hindcast_config = build_hindcast_config(pipeline_config)
    member_results = run_ensemble(
        primary, CURRENTS_PATH, WIND_PATH, ACQUIRED_AT, hindcast_config,
        n_members=hindcast_config["hindcast"]["n_members_full"],
    )
    field_ds = build_origin_field(
        member_results,
        grid_resolution_deg=hindcast_config["hindcast"]["field"]["grid_resolution_deg"],
        time_step_minutes=hindcast_config["hindcast"]["field"]["time_step_minutes"],
        gaussian_bandwidth_deg=hindcast_config["hindcast"]["field"]["gaussian_bandwidth_deg"],
        seed=hindcast_config["seed"],
    )
    print(f"  field dims={dict(field_ds.sizes)}, sum={float(field_ds['probability'].values.sum()):.6f}")

    print("Generating the synthetic AIS scenario...")
    tracks = generate_demo_scenario(field_ds, AIS_CONFIG, seed=scoring_config["seed"])
    print(f"  {len(tracks)} vessel(s)")

    print("Eliminating and scoring...")
    survivors, eliminations = eliminate_and_survive(tracks, field_ds, scoring_config)
    scores = score_vessels(survivors, field_ds, slick_features, scoring_config)
    score_by_mmsi = {s.mmsi: s for s in scores}
    elim_by_mmsi = {e.mmsi: e for e in eliminations}
    print(f"  {len(survivors)} survivor(s), {len(eliminations)} elimination(s)")
    print(f"  rank 1: {scores[0].mmsi}" if scores else "  no survivors scored")

    vessels_json = []
    for track in tracks:
        score = score_by_mmsi.get(track.mmsi)
        elim = elim_by_mmsi.get(track.mmsi)
        vessels_json.append(
            {
                "mmsi": track.mmsi,
                "vessel_type": track.vessel_type,
                "points": [ais_point_to_json(p) for p in track.points],
                "dark_gaps": [dark_gap_to_json(g) for g in track.dark_gaps],
                "status": "eliminated" if elim else "survivor",
                "elimination": {"reason": elim.reason, "rule": elim.rule} if elim else None,
                "score": (
                    {
                        "total": score.total,
                        "factors": score.factors,
                        "rank": score.rank,
                        "narrative": score.narrative,
                    }
                    if score
                    else None
                ),
            }
        )

    detections_json = []
    for d in oil_detections:
        gate = gate_by_id[d.detection_id]
        detections_json.append(
            {
                "detection_id": d.detection_id,
                "class_name": d.class_name,
                "geometry": d.geometry,
                "mean_class_prob": d.mean_class_prob,
                "pixel_area": d.pixel_area,
                "gate": {"wind_speed_ms": gate.wind_speed_ms, "verdict": gate.verdict, "reason": gate.reason},
            }
        )

    bundle = {
        "case_id": "SLICKTRACE-DEMO-0001",
        "generated_at": _iso(datetime.datetime.utcnow()),
        "status_note": (
            "Demo scenario built entirely from committed offline fixtures: a synthetic "
            "SAR scene, synthetic wind/current forcing, and synthetic AIS traffic with a "
            "known injected culprit. Every stage below (detection, wind gate, "
            "characterisation, backward drift ensemble, elimination, scoring) ran for "
            "real on that fixture data. See PLAN.md section 4A for what is real vs "
            "synthetic and why."
        ),
        "incident_context": {
            "status": incident_context["status"],
            "source_reference": incident_context["source_reference"].strip(),
        },
        "scene": {
            **build_scene_meta(SCENE_PATH, SCENE_ID, ACQUIRED_AT),
            # The frontend fetches the image itself from /api/scene_preview.png
            # (or /data/scene_preview.png offline); this is just where to put it.
            "preview": {
                "bounds": scene_preview["bounds"],
                "width": scene_preview["width"],
                "height": scene_preview["height"],
                "display_db_window": scene_preview["display_db_window"],
                "note": scene_preview["note"],
            },
        },
        "detections": detections_json,
        "primary_detection_id": primary.detection_id,
        "slick_features": json.loads(slick_features.model_dump_json()),
        "origin_field": origin_field_to_json(field_ds),
        "vessels": vessels_json,
        "eliminations": [json.loads(e.model_dump_json()) for e in eliminations],
        "suspects": [json.loads(s.model_dump_json()) for s in scores],
        "culprit_mmsi": "419000001",
    }

    with open(OUT_PATH, "w") as f:
        json.dump(bundle, f)
    import os

    size_kb = os.path.getsize(OUT_PATH) / 1024
    print(f"wrote {OUT_PATH} ({size_kb:.0f} KB)")

    print("Rendering the case dossier PDF...")
    with open("config/scoring.yaml") as f:
        scoring_config_text = f.read()
    artifact_paths = {
        "SAR scene (fixture)": SCENE_PATH,
        "ocean currents (fixture)": CURRENTS_PATH,
        "wind field (fixture)": WIND_PATH,
        "detection model weights": "data/models/oil-spill-deeplab/model.keras",
        "demo bundle": OUT_PATH,
    }
    render_dossier(bundle, scoring_config_text, artifact_paths, DOSSIER_OUT_PATH)
    print(f"wrote {DOSSIER_OUT_PATH}")


if __name__ == "__main__":
    main()
