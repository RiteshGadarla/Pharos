"""Contract tests for services/core/schemas.py. See PLAN.md sections 4 and 16."""

import pytest
from pydantic import ValidationError

from services.core.schemas import (
    AISPoint,
    AISTrack,
    DarkGap,
    Detection,
    Elimination,
    GateResult,
    OriginField,
    SceneMeta,
    SlickFeatures,
    SuspectScore,
)


def test_suspect_score_factors_must_sum_to_total():
    score = SuspectScore(
        mmsi="419000001",
        total=0.75,
        factors={"field_integral": 0.5, "dark_overlap": 0.25},
        rank=1,
        narrative="Test narrative.",
    )
    assert score.total == pytest.approx(0.75)


def test_suspect_score_rejects_mismatched_factors():
    with pytest.raises(ValidationError):
        SuspectScore(
            mmsi="419000001",
            total=1.0,
            factors={"field_integral": 0.5, "dark_overlap": 0.25},
            rank=1,
            narrative="Test narrative.",
        )


def test_suspect_score_allows_floating_point_tolerance():
    # 0.1 + 0.2 != 0.3 exactly in binary floating point; the model must
    # tolerate that without requiring exact equality.
    score = SuspectScore(
        mmsi="419000001",
        total=0.3,
        factors={"a": 0.1, "b": 0.2},
        rank=1,
        narrative="Test narrative.",
    )
    assert score.total == pytest.approx(0.3)


def test_elimination_reason_required_and_non_empty():
    with pytest.raises(ValidationError):
        Elimination(mmsi="419000002", reason="", rule="NO_TEMPORAL_OVERLAP")

    elim = Elimination(
        mmsi="419000002",
        reason="This vessel had no recorded position anywhere in the origin field's time window.",
        rule="NO_TEMPORAL_OVERLAP",
    )
    assert elim.reason


@pytest.mark.parametrize(
    "model,payload",
    [
        (
            SceneMeta,
            dict(
                scene_id="S1A_IW_GRDH_TEST",
                acquired_at="2026-01-15T02:30:00Z",
                bbox=(68.0, 6.0, 97.0, 24.0),
                crs="EPSG:4326",
                source_path="data/raw/s1/S1A_IW_GRDH_TEST.zip",
            ),
        ),
        (
            Detection,
            dict(
                detection_id="det-001",
                scene_id="S1A_IW_GRDH_TEST",
                class_name="oil",
                geometry={"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]},
                mean_class_prob=0.87,
                pixel_area=4200,
            ),
        ),
        (
            SlickFeatures,
            dict(
                detection_id="det-001",
                area_km2=12.3,
                perimeter_km=25.4,
                complexity_ratio=2.1,
                major_axis_deg=45.0,
                elongation=6.2,
                mean_backscatter_db=-22.5,
                contrast_db=-6.1,
                age_band="fresh",
                age_reasoning="High contrast and compact geometry indicate a recently discharged slick.",
            ),
        ),
        (
            GateResult,
            dict(
                detection_id="det-001",
                wind_speed_ms=6.4,
                verdict="accept",
                reason="Wind speed within the valid capillary wave damping window.",
            ),
        ),
        (
            OriginField,
            dict(
                field_id="field-001",
                detection_id="det-001",
                path="data/processed/origin_fields/field-001.nc",
                t_min="2026-01-13T02:30:00Z",
                t_max="2026-01-15T02:30:00Z",
                n_members=30,
                seed=26143,
            ),
        ),
    ],
)
def test_model_round_trips_through_json(model, payload):
    instance = model(**payload)
    restored = model.model_validate_json(instance.model_dump_json())
    assert restored == instance


def test_ais_track_with_dark_gap_round_trips_through_json():
    track = AISTrack(
        mmsi="419000001",
        vessel_type="tanker",
        points=[
            AISPoint(ts="2026-01-14T10:00:00Z", lat=10.0, lon=75.0, sog=12.0, cog=270.0),
            AISPoint(ts="2026-01-14T10:20:00Z", lat=10.05, lon=74.9, sog=4.0, cog=280.0),
        ],
        dark_gaps=[
            DarkGap(
                start="2026-01-14T10:20:00Z",
                end="2026-01-14T11:10:00Z",
                duration_min=50.0,
                entry_point=(74.9, 10.05),
                exit_point=(74.7, 10.1),
                envelope={"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]},
            )
        ],
    )
    restored = AISTrack.model_validate_json(track.model_dump_json())
    assert restored == track
    assert len(restored.dark_gaps) == 1


# --- Contracts added in the current PLAN.md revision (section 4) ---


def test_ship_target_defaults_to_unmatched():
    """An unmatched target is the interesting one, and it is what a
    freshly extracted target is until crosscheck/radar.py says
    otherwise. Defaulting the other way would quietly assert that every
    hull was accounted for."""
    from services.core.schemas import ShipTarget

    target = ShipTarget(
        target_id="t-1", scene_id="S-1", centroid=(68.0, 17.0),
        pixel_area=64, mean_backscatter_db=-4.0,
    )
    assert target.matched_mmsi is None
    assert target.match_confidence == 0.0
    assert ShipTarget.model_validate_json(target.model_dump_json()) == target


def test_marpol_discharge_must_be_an_ordered_band():
    """PLAN.md section 4 contract rule: est_discharge_l_per_nm is a
    band, never a scalar. SAR cannot see slick thickness, so the volume
    behind this rate is only ever known to an order of magnitude."""
    import pytest as _pytest
    from pydantic import ValidationError

    from services.core.schemas import MarpolAssessment

    ok = MarpolAssessment(mmsi="419000001", est_discharge_l_per_nm=(12.0, 200.0), flag="conditions_not_met")
    assert ok.est_discharge_l_per_nm[1] > ok.est_discharge_l_per_nm[0]
    assert MarpolAssessment.model_validate_json(ok.model_dump_json()) == ok

    with _pytest.raises(ValidationError):
        MarpolAssessment(mmsi="419000001", est_discharge_l_per_nm=(200.0, 12.0), flag="conditions_not_met")


def test_case_verdict_requires_a_reason():
    """A verdict class with no reasoning is a label, and a label is not
    evidence. Empty reasoning must not construct."""
    import pytest as _pytest
    from pydantic import ValidationError

    from services.core.schemas import CaseVerdict

    with _pytest.raises(ValidationError):
        CaseVerdict(case_id="C-1", verdict="ATTRIBUTED", reasoning="")


def test_integrity_flag_severity_is_bounded():
    import pytest as _pytest
    from pydantic import ValidationError

    from services.core.schemas import IntegrityFlag

    with _pytest.raises(ValidationError):
        IntegrityFlag(kind="no_imo", at="2026-01-14T10:00:00Z", detail="d", severity=1.5)


def test_suspect_score_still_sums_with_the_two_new_factors():
    """The invariant that makes the score auditable, re-checked now that
    F7 and F8 are in the factor set."""
    from services.core.schemas import SuspectScore

    factors = {
        "field_integral": 1.2, "dark_overlap": 0.8, "axis_alignment": 0.3,
        "speed_anomaly": 0.1, "course_anomaly": -0.2, "vessel_plausibility": 0.05,
        "ais_integrity": 0.4, "radar_confirmed_dark": 2.1,
    }
    score = SuspectScore(
        mmsi="419000001", total=sum(factors.values()), factors=factors, rank=1, narrative="n",
        radar_support="t-unmatched",
    )
    assert score.radar_support == "t-unmatched"
    assert SuspectScore.model_validate_json(score.model_dump_json()) == score


def test_optical_corroboration_has_exactly_three_states():
    import pytest as _pytest
    from pydantic import ValidationError

    from services.core.schemas import OpticalCorroboration

    for status in ("agree", "disagree", "no_coverage"):
        OpticalCorroboration(detection_id="d", status=status, reasoning="r")
    with _pytest.raises(ValidationError):
        OpticalCorroboration(detection_id="d", status="probably", reasoning="r")


def test_origin_field_records_which_kernel_produced_it():
    from services.core.schemas import OriginField

    field = OriginField(
        field_id="f-1", detection_id="d-1", path="x.nc",
        t_min="2026-01-13T02:30:00Z", t_max="2026-01-15T02:30:00Z",
        n_members=30, seed=26143, kernel="leeway",
    )
    assert OriginField.model_validate_json(field.model_dump_json()).kernel == "leeway"
