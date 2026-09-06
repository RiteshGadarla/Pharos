"""Produces the precomputed demo bundle in data/precomputed/. See PLAN.md section 20.

Runs the real pipeline once, offline, on the committed fixtures (no real
Sentinel-1 scene yet, PLAN.md section 4A item 4; no real AIS, section 10):

  detection (render/tile/infer/polygonize) -> wind gate -> optical
  corroboration -> characterise -> backward drift ensemble (pluggable
  kernel) -> origin probability field -> synthetic AIS scenario -> AIS
  integrity flags -> SAR ship target cross check -> elimination ->
  scoring -> verdict -> MARPOL assessment -> infrastructure flag ->
  accumulating ledgers

and writes one self-contained JSON bundle, data/precomputed/demo_bundle.json,
that the frontend loads with no live pipeline calls and no database. This
is what DEMO_MODE=offline serves (PLAN.md section 20).

Run from backend/: .venv/bin/python scripts/seed_demo.py
"""

from __future__ import annotations

import datetime
import json

import xarray as xr
import yaml
from rasterio.warp import transform_bounds
import rasterio

from services.core.ais.integrity import annotate_integrity
from services.core.ais.synthetic import generate_demo_scenario, inject_ship_targets
from services.core.characterize.age import with_age
from services.core.characterize.geometry import compute_slick_features_dict
from services.core.corroborate.optical import corroborate
from services.core.crosscheck.infrastructure import check_infrastructure_overlap
from services.core.crosscheck.radar import run_cross_check
from services.core.dossier.render import render_dossier
from services.core.forecast.forward import forecast_config, run_forecast
from services.core.forcing import sample_at, subsample_forcing
from services.core.gate.wind import gate_detections, load_wind_field
from services.core.hindcast.ensemble import resolve_kernel, run_ensemble
from services.core.hindcast.field import build_origin_field
from services.core.ledger.completeness import append_row as append_completeness_row
from services.core.ledger.completeness import build_row as build_completeness_row
from services.core.ledger.dark import append_rows as append_dark_rows
from services.core.ledger.dark import build_rows as build_dark_rows
from services.core.legal.marpol import assess as assess_marpol
from services.core.preview import render_scene_preview
from services.core.schemas import Detection
from services.core.scoring.age_window import describe_window, window_for_band
from services.core.scoring.temporal import describe_factor, describe_timing
from services.core.scoring.case_build import build_case
from services.core.scoring.eliminate import eliminate_and_survive
from services.core.scoring.engine import score_vessels
from services.core.scoring.verdict import assign_verdict
from services.detection.app import load_config as load_pipeline_config
from services.detection.app import run_pipeline

SCENE_PATH = "data/fixtures/synthetic_scene.tif"
CURRENTS_PATH = "data/fixtures/synthetic_currents.nc"
WIND_PATH = "data/fixtures/synthetic_wind_offshore.nc"
OUT_PATH = "data/precomputed/demo_bundle.json"
DOSSIER_OUT_PATH = "data/precomputed/case_dossier.pdf"
SCENE_PREVIEW_OUT_PATH = "data/precomputed/scene_preview.png"

SCENE_ID = "DRISHTA-DEMO-0001"
ACQUIRED_AT = datetime.datetime(2026, 1, 15, 2, 30)

# Recorded into both drift fields and carried to the dossier's
# provenance page. Named once so the backward and the forward field
# cannot disagree about what forced them.
FORCING_SOURCE = "offline synthetic fixtures (data/fixtures/), not real CMEMS or ERA5"

# The demo precompute runs the hindcast exactly as config/pipeline.yaml
# specifies it, with no overrides.
#
# It used to cut the run down to 8 members over a 6 hour horizon for
# speed, and that quietly broke the thing the product is built around.
# Over 6 hours the ensemble barely diverges, so the origin field came out
# the same size at every timestep: scrubbing back from acquisition showed
# a cloud that drifted but never grew, when the whole argument of PLAN.md
# section 12's signature interaction is that it should bloom as you go
# back and knowledge runs out. On the configured 48 hour horizon the
# particle spread runs from 0.2 km at acquisition to 5.5 km two days
# back, which is the behaviour the interaction depends on.
#
# The cost is a slower precompute, which is the right trade for a step
# that runs once and is committed to a JSON file.
HINDCAST_OVERRIDES: dict = {}

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


def load_marpol_config() -> dict:
    with open("config/marpol.yaml") as f:
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
        "sensor": "S1",
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
    hindcast_cfg["field"] = {**hindcast_cfg.get("field", {}), **HINDCAST_OVERRIDES.get("field", {})}
    return {"seed": pipeline_config["seed"], "hindcast": hindcast_cfg}


def origin_field_to_json(field_ds: xr.Dataset) -> dict:
    times = [pd_ts for pd_ts in field_ds["time"].values]
    # Only a forward run carries these. A kernel that runs out of forcing
    # stops quietly, so the achieved horizon has to travel with the field
    # or the UI will caption a truncated forecast with the horizon that
    # was asked for rather than the one that was produced.
    horizon: dict = {}
    if "achieved_horizon_hours" in field_ds.attrs:
        horizon = {
            "requested_horizon_hours": float(field_ds.attrs["requested_horizon_hours"]),
            "achieved_horizon_hours": float(field_ds.attrs["achieved_horizon_hours"]),
            "horizon_truncated": bool(int(field_ds.attrs.get("horizon_truncated", 0))),
        }
    return {
        **horizon,
        # The horizon the run covered, as opposed to the span of the
        # binned time axis. See build_origin_field for why they differ.
        "span_hours": float(field_ds.attrs.get("horizon_hours", 0.0)),
        "seed": int(field_ds.attrs["seed"]),
        "n_members": int(field_ds.attrs["n_members"]),
        # Which DriftKernel produced this field, and from what forcing.
        # Both come from the field's own NetCDF attributes rather than
        # from the caller, so the bundle cannot disagree with the file.
        "kernel": str(field_ds.attrs.get("kernel", "openoil")),
        "forcing_source": str(field_ds.attrs.get("forcing_source", "unspecified")),
        # Which way time ran. The frontend colours and labels the two
        # fields differently, and nothing but this tells them apart.
        "direction": str(field_ds.attrs.get("direction", "backward")),
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
    kernel = resolve_kernel(hindcast_config)
    print(f"  drift kernel: {kernel.name}")
    member_results = run_ensemble(
        primary, CURRENTS_PATH, WIND_PATH, ACQUIRED_AT, hindcast_config,
        n_members=hindcast_config["hindcast"]["n_members_full"],
        kernel=kernel,
    )
    field_ds = build_origin_field(
        member_results,
        grid_resolution_deg=hindcast_config["hindcast"]["field"]["grid_resolution_deg"],
        time_step_minutes=hindcast_config["hindcast"]["field"]["time_step_minutes"],
        gaussian_bandwidth_deg=hindcast_config["hindcast"]["field"]["gaussian_bandwidth_deg"],
        seed=hindcast_config["seed"],
        kernel=kernel.name,
        forcing_source=FORCING_SOURCE,
    )
    print(f"  field dims={dict(field_ds.sizes)}, sum={float(field_ds['probability'].values.sum()):.6f}")

    # The other half of the drift picture, PLAN.md section 15. Same
    # kernel, same seed particles, positive time step. It is the
    # response planning product and never touches the scoring below.
    print("Running the forward forecast...")
    forecast_cfg = forecast_config(pipeline_config)
    forecast_ds = run_forecast(
        primary, CURRENTS_PATH, WIND_PATH, ACQUIRED_AT,
        {**hindcast_config, "forecast": {**forecast_cfg, "forcing_source": FORCING_SOURCE}},
        kernel=kernel,
    )
    print(
        f"  +{forecast_cfg['forward_horizon_hours']}h, dims={dict(forecast_ds.sizes)}, "
        f"sum={float(forecast_ds['probability'].values.sum()):.6f}"
    )

    print("Subsampling the forcing fields for the console...")
    scene_meta_bbox = build_scene_meta(SCENE_PATH, SCENE_ID, ACQUIRED_AT)["bbox"]
    field_times = [_to_pydatetime(t) for t in field_ds["time"].values]
    forecast_times = [_to_pydatetime(t) for t in forecast_ds["time"].values]
    # Cropped to the area the case occupies, not the whole fixture
    # domain: the grid budget spent on empty ocean is what leaves the
    # console with six arrows and 22 km between them.
    case_w = min(min(of_lons := list(field_ds["lon"].values)), min(forecast_ds["lon"].values), scene_meta_bbox[0])
    case_e = max(max(of_lons), max(forecast_ds["lon"].values), scene_meta_bbox[2])
    case_s = min(min(of_lats := list(field_ds["lat"].values)), min(forecast_ds["lat"].values), scene_meta_bbox[1])
    case_n = max(max(of_lats), max(forecast_ds["lat"].values), scene_meta_bbox[3])
    margin = 0.1
    forcing = subsample_forcing(
        CURRENTS_PATH, WIND_PATH,
        t_min=min(field_times), t_max=max(forecast_times),
        bbox=(case_w - margin, case_s - margin, case_e + margin, case_n + margin),
    )
    from shapely.geometry import shape as _shape

    slick_centroid = _shape(primary.geometry).centroid
    at_slick = sample_at(forcing, slick_centroid.y, slick_centroid.x, ACQUIRED_AT)
    print(
        f"  {len(forcing['time'])} steps on a {len(forcing['lat'])}x{len(forcing['lon'])} grid; "
        f"at the slick: wind {at_slick.get('wind_speed')} m/s, "
        f"current {at_slick.get('current_speed')} m/s, "
        f"SST {at_slick.get('sst_c')} C, air {at_slick.get('air_temp_c')} C"
    )

    print("Generating the synthetic AIS scenario...")
    # Where in the backward window the discharge is placed, taken from
    # the slick's own age band rather than chosen. The characterisation
    # measured this scene's contrast and complexity; the age window
    # config turns that band into a range of plausible origin hours; the
    # scenario puts the culprit in the middle of that range.
    #
    # This is what makes the demo exercise the hindcast. The origin used
    # to come from the field's global argmax, which always lands within
    # a timestep of acquisition, so the culprit sat on the slick's
    # observed position and 47 of the 48 reconstructed hours went unused.
    age_cfg = scoring_config.get("age_origin_window", {})
    window_lo, window_hi = window_for_band(slick_features.age_band, age_cfg)
    origin_lag_hours = (window_lo + window_hi) / 2.0
    print(f"  origin window from the {slick_features.age_band} slick: "
          f"{window_lo:.0f} to {window_hi:.0f} h before acquisition, "
          f"culprit placed at -{origin_lag_hours:.0f} h")
    tracks = generate_demo_scenario(
        field_ds, AIS_CONFIG, seed=scoring_config["seed"],
        origin_lag_hours=origin_lag_hours, acquired_at=ACQUIRED_AT,
    )
    tracks = annotate_integrity(tracks, scoring_config.get("integrity", {}))
    n_flags = sum(len(t.integrity_flags) for t in tracks)
    print(f"  {len(tracks)} vessel(s), {n_flags} AIS integrity flag(s)")

    print("Cross checking SAR ship targets against AIS...")
    ship_targets = inject_ship_targets(tracks, field_ds, ACQUIRED_AT)
    cross_check = run_cross_check(
        ship_targets, tracks, field_ds, ACQUIRED_AT, pipeline_config.get("radar_crosscheck", {})
    )
    eps = scoring_config.get("verdict", {}).get("eps", 1e-6)
    print(
        f"  {len(cross_check.targets)} target(s): {len(cross_check.matched)} matched, "
        f"{len(cross_check.unmatched)} unmatched, "
        f"{len(cross_check.unmatched_in_field(eps))} unmatched inside the origin field"
    )

    print("Eliminating and scoring...")
    survivors, eliminations = eliminate_and_survive(tracks, field_ds, scoring_config)
    scores = score_vessels(
        survivors, field_ds, slick_features, scoring_config,
        cross_check=cross_check, acquired_at=ACQUIRED_AT,
    )
    score_by_mmsi = {s.mmsi: s for s in scores}
    elim_by_mmsi = {e.mmsi: e for e in eliminations}
    print(f"  {len(survivors)} survivor(s), {len(eliminations)} elimination(s)")
    print(f"  rank 1: {scores[0].mmsi}" if scores else "  no survivors scored")

    # The case rebuilt one class of evidence at a time, plus the
    # leave-one-out test of whether any single factor decides it.
    # PLAN.md section 22: this is what turns the ranking from a result
    # into an argument a room can interrogate.
    print("Rebuilding the case step by step...")
    temporal_cfg = scoring_config.get("temporal_consistency", {})
    vessel_timing = {
        t.mmsi: describe_timing(
            t, field_ds, slick_features.age_band, ACQUIRED_AT, age_cfg, temporal_cfg
        )
        for t in survivors
    }
    _in_band = sum(1 for v in vessel_timing.values() if v["within_band"])
    _in_margin = sum(1 for v in vessel_timing.values() if v["within_uncertainty"])
    print(f"  timing: {_in_band} of {len(vessel_timing)} survivors peak inside the origin window, "
          f"{_in_margin} inside the band's own uncertainty")

    case = build_case(
        survivors, eliminations, field_ds, slick_features, scoring_config,
        cross_check=cross_check, acquired_at=ACQUIRED_AT,
        all_tracks=tracks, slick_geometry=primary.geometry,
    )
    flips = [s["label"] for s in case["steps"] if s["lead_changed"]]
    print(f"  leader changes at: {', '.join(flips) if flips else 'never'}")
    print(f"  settles at: {case['stabilises_at_step']}")
    print(f"  decisive factors: {case['decisive_factors'] or 'none, no single factor decides it'}")
    for baseline in case["baselines"]:
        agree = "agrees" if baseline["agrees"] else "DIFFERS"
        print(f"  baseline {baseline['key']}: {baseline['answer']} ({agree})")

    print("Checking the origin envelope against offshore infrastructure...")
    infrastructure = check_infrastructure_overlap(field_ds, pipeline_config.get("infrastructure", {}))
    print(f"  flagged: {infrastructure.flagged}")

    print("Assigning the case verdict...")
    vessels_with_dark_gaps = {t.mmsi for t in tracks if t.dark_gaps}
    verdict = assign_verdict(
        case_id=SCENE_ID,
        scores=scores,
        cross_check=cross_check,
        vessels_with_dark_gaps=vessels_with_dark_gaps,
        verdict_config=scoring_config.get("verdict", {}),
        infrastructure_flag=infrastructure.flagged,
    )
    print(f"  verdict: {verdict.verdict}")

    print("Evaluating MARPOL Annex I conditions for the top suspect...")
    marpol_config = load_marpol_config()
    marpol = None
    if scores:
        top_track = next((t for t in tracks if t.mmsi == scores[0].mmsi), None)
        if top_track is not None:
            marpol = assess_marpol(top_track, field_ds, slick_features, marpol_config)
            print(f"  flag: {marpol.flag}")

    print("Corroborating against optical imagery...")
    # No optical scene is held offline for this fixture region, so this
    # emits no_coverage with its reasoning. That is one of the three
    # honest states in PLAN.md section 7, not a stub: the reasoning
    # names SAR primacy, and the state changes on its own the moment a
    # coincident scene is available.
    optical = corroborate(primary, ACQUIRED_AT, [], pipeline_config.get("optical", {}))
    print(f"  status: {optical.status}")

    print("Appending to the accumulating ledgers...")
    dark_rows = build_dark_rows(tracks, SCENE_ID, SCENE_ID, cross_check)
    append_dark_rows(dark_rows)
    scene_meta = build_scene_meta(SCENE_PATH, SCENE_ID, ACQUIRED_AT)
    append_completeness_row(
        build_completeness_row(
            SCENE_ID, ACQUIRED_AT, tuple(scene_meta["bbox"]), "S1", cross_check, case_id=SCENE_ID
        )
    )
    print(f"  {len(dark_rows)} dark period row(s), 1 completeness row")

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
                "integrity_flags": [
                    {
                        "kind": f.kind,
                        "at": _iso(f.at),
                        "detail": f.detail,
                        "severity": f.severity,
                    }
                    for f in track.integrity_flags
                ],
                "status": "eliminated" if elim else "survivor",
                "elimination": {"reason": elim.reason, "rule": elim.rule} if elim else None,
                "score": (
                    {
                        "total": score.total,
                        "factors": score.factors,
                        "rank": score.rank,
                        "narrative": score.narrative,
                        "radar_support": score.radar_support,
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
        "case_id": "DRISHTA-DEMO-0001",
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
            **scene_meta,
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
        # The origin window the slick's condition implies, and the only
        # evidence in the case about WHEN the discharge happened. F1 and
        # F2 weight the field's time axis by it. See PLAN.md section 12.
        "origin_window": {
            "age_band": slick_features.age_band,
            "earliest_hours_before": window_lo,
            "latest_hours_before": window_hi,
            "taper_hours": float(age_cfg.get("taper_hours", 6.0)),
            "floor_weight": float(age_cfg.get("floor_weight", 0.15)),
            "statement": describe_window(slick_features.age_band, age_cfg),
            # Beyond this many hours past each edge the window stops
            # being treated as though it held exactly. Inside it, a
            # vessel scores as if it were in the band: the band comes
            # from contrast and complexity, which do not resolve a
            # couple of hours, so burying the vessels that passed just
            # outside would claim a precision the radiometry has not
            # got. See scoring/temporal.py.
            "band_uncertainty_hours": float(temporal_cfg.get("band_uncertainty_hours", 3.0)),
            "falloff_hours": float(temporal_cfg.get("falloff_hours", 8.0)),
            "timing_statement": describe_factor(slick_features.age_band, age_cfg, temporal_cfg),
        },
        # Per vessel: the hour it had its best opportunity to be the
        # source, how far that sits from the origin window, and the
        # words explaining F9's bar. A bar without a reason is a bar
        # asking to be trusted.
        "vessel_timing": vessel_timing,
        "origin_field": origin_field_to_json(field_ds),
        # Wind, current and temperature over the case window. Context for
        # the drift rather than evidence: it explains why the origin
        # field leans where it does. Subsampled from the same NetCDF the
        # ensemble integrated, never resampled, so every arrow the console
        # draws is a value the forcing file actually holds.
        "forcing": forcing,
        # Where the oil goes next, PLAN.md section 15. Same structure as
        # the origin field and told apart only by its "direction", which
        # is why the field itself carries it rather than the key name.
        "forecast_field": origin_field_to_json(forecast_ds),
        "vessels": vessels_json,
        "eliminations": [json.loads(e.model_dump_json()) for e in eliminations],
        "suspects": [json.loads(s.model_dump_json()) for s in scores],
        "case_build": case,
        "culprit_mmsi": "419000001",
        "optical": json.loads(optical.model_dump_json()),
        "verdict": json.loads(verdict.model_dump_json()),
        "marpol": json.loads(marpol.model_dump_json()) if marpol else None,
        "infrastructure": {
            "flagged": infrastructure.flagged,
            "mass_within_radius": infrastructure.mass_within_radius,
            "installations": infrastructure.installations,
            "statement": infrastructure.statement,
        },
        "radar_crosscheck": {
            "match_radius_m": pipeline_config.get("radar_crosscheck", {}).get("match_radius_m"),
            "n_targets": len(cross_check.targets),
            "n_matched": len(cross_check.matched),
            "n_unmatched": len(cross_check.unmatched),
            "targets": [
                {
                    "target_id": t.target_id,
                    "centroid": list(t.centroid),
                    "pixel_area": t.pixel_area,
                    "mean_backscatter_db": t.mean_backscatter_db,
                    "matched_mmsi": t.matched_mmsi,
                    "match_distance_m": t.match_distance_m,
                    "match_confidence": t.match_confidence,
                    "field_mass": cross_check.field_mass.get(t.target_id),
                    "envelope_hits": cross_check.envelope_hits.get(t.target_id, []),
                }
                for t in cross_check.targets
            ],
            "caveats": [
                "Sentinel-1 ship detection at GRD resolution misses small vessels.",
                "Not every unmatched target is evasion. Vessels below AIS carriage requirements, fishing craft and buoys all appear. Unmatched never means guilty.",
                "The match is made at the acquisition instant only, which is a single moment in time.",
                "In this demo the ship targets are synthetic, generated alongside the synthetic AIS, because the fixture scene contains no real hulls. The matching, the envelope test and the field test all run for real on them.",
            ],
        },
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
