"""The architecture claim, tested end to end. See PLAN.md sections 9.1
and 21:

  "A test that the null drift kernel produces a field on which every
   downstream stage runs unchanged."

This is the test that decides whether "the drift kernel is a plug in" is
a real property of the code or a sentence on a slide. The null kernel
holds every particle at its seed position: no forcing data, no
OpenDrift, no oil physics at all. If elimination, scoring, the radar
cross check, the verdict and the MARPOL layer all still run on the field
it produces, the engine is genuinely event agnostic.
"""

from __future__ import annotations

import datetime

import numpy as np
import yaml

from services.core.ais.integrity import annotate_integrity
from services.core.crosscheck.radar import run_cross_check
from services.core.drift.null import NullKernel
from services.core.hindcast.ensemble import run_ensemble
from services.core.hindcast.field import build_origin_field
from services.core.legal.marpol import assess as assess_marpol
from services.core.schemas import AISPoint, AISTrack, Detection, ShipTarget, SlickFeatures
from services.core.scoring.eliminate import eliminate_and_survive
from services.core.scoring.engine import score_vessels
from services.core.scoring.verdict import assign_verdict

ACQUIRED_AT = datetime.datetime(2026, 1, 15, 2, 30)

DETECTION = Detection(
    detection_id="det-null-1",
    scene_id="SCENE-NULL",
    class_name="oil",
    geometry={
        "type": "Polygon",
        "coordinates": [[[67.98, 16.98], [67.98, 17.02], [68.02, 17.02], [68.02, 16.98], [67.98, 16.98]]],
    },
    mean_class_prob=0.9,
    pixel_area=100,
)

SLICK = SlickFeatures(
    detection_id="det-null-1", area_km2=1.0, perimeter_km=4.0, complexity_ratio=1.2,
    major_axis_deg=45.0, elongation=3.0, mean_backscatter_db=-25.0, contrast_db=-10.0,
    age_band="fresh", age_reasoning="test fixture",
)

CONFIG = {
    "seed": 26143,
    "hindcast": {
        "kernel": "null",
        "n_members_full": 3,
        "particles_per_member": 20,
        "backward_horizon_hours": 6,
        "wind_drift_factor_range": [0.02, 0.04],
        "current_perturbation_range": [0.05, 0.15],
        "horizontal_diffusivity_range": [1.0, 10.0],
        "seed_time_jitter_minutes": 15,
        "field": {"grid_resolution_deg": 0.005, "time_step_minutes": 30, "gaussian_bandwidth_deg": 0.008},
    },
}


def _field():
    """The whole point: a field with no forcing data anywhere in sight."""
    members = run_ensemble(
        DETECTION, "no/such/currents.nc", "no/such/wind.nc", ACQUIRED_AT, CONFIG,
        kernel=NullKernel(),
    )
    return build_origin_field(
        members,
        grid_resolution_deg=CONFIG["hindcast"]["field"]["grid_resolution_deg"],
        time_step_minutes=CONFIG["hindcast"]["field"]["time_step_minutes"],
        gaussian_bandwidth_deg=CONFIG["hindcast"]["field"]["gaussian_bandwidth_deg"],
        seed=CONFIG["seed"],
        kernel="null",
    )


def _vessels():
    """One vessel over the seed footprint, one far away."""
    over = AISTrack(
        mmsi="419000001", vessel_type="tanker",
        points=[
            AISPoint(ts=ACQUIRED_AT - datetime.timedelta(hours=6) + datetime.timedelta(minutes=30 * i),
                     lat=17.0, lon=68.0, sog=3.0, cog=45.0)
            for i in range(13)
        ],
    )
    away = AISTrack(
        mmsi="419000002", vessel_type="cargo",
        points=[
            AISPoint(ts=ACQUIRED_AT - datetime.timedelta(hours=6) + datetime.timedelta(minutes=30 * i),
                     lat=18.5, lon=69.5, sog=12.0, cog=90.0)
            for i in range(13)
        ],
    )
    return [over, away]


def test_the_null_kernel_field_is_a_valid_origin_field():
    field_ds = _field()
    assert float(field_ds["probability"].values.sum()) == 1.0 or np.isclose(
        float(field_ds["probability"].values.sum()), 1.0
    )
    assert field_ds.sizes["time"] > 1  # a real time axis, even though nothing moved
    assert field_ds.attrs["kernel"] == "null"


def test_every_downstream_stage_runs_unchanged_on_a_null_kernel_field():
    field_ds = _field()
    with open("config/scoring.yaml") as f:
        scoring_config = yaml.safe_load(f)
    with open("config/marpol.yaml") as f:
        marpol_config = yaml.safe_load(f)

    tracks = annotate_integrity(_vessels(), scoring_config.get("integrity", {}))

    targets = [
        ShipTarget(target_id="t-1", scene_id="SCENE-NULL", centroid=(68.0, 17.0),
                   pixel_area=50, mean_backscatter_db=-4.0)
    ]
    cross_check = run_cross_check(targets, tracks, field_ds, ACQUIRED_AT, {"match_radius_m": 1500.0})

    survivors, eliminations = eliminate_and_survive(tracks, field_ds, scoring_config)
    assert survivors, "the vessel over the seed footprint must survive elimination"
    assert all(e.reason for e in eliminations)

    scores = score_vessels(survivors, field_ds, SLICK, scoring_config, cross_check=cross_check)
    assert scores
    assert scores[0].rank == 1

    verdict = assign_verdict(
        "CASE-NULL", scores, cross_check, {t.mmsi for t in tracks if t.dark_gaps},
        scoring_config.get("verdict", {}),
    )
    assert verdict.verdict in {"ATTRIBUTED", "RANKED", "DARK_CONFIRMED"}

    top_track = next(t for t in tracks if t.mmsi == scores[0].mmsi)
    assessment = assess_marpol(top_track, field_ds, SLICK, marpol_config)
    assert assessment.flag in {"conditions_not_met", "conditions_met", "insufficient_data"}


def test_a_fixed_position_event_produces_a_field_that_does_not_spread():
    """What a null kernel is for. The field should stay put across the
    whole backward window: for a fixed source, the origin envelope does
    not widen with time, and asserting otherwise would be inventing
    uncertainty the physics does not support."""
    field_ds = _field()
    prob = field_ds["probability"].values
    first = prob[0] / prob[0].sum()
    last = prob[-1] / prob[-1].sum()
    np.testing.assert_allclose(first, last, atol=1e-9)
