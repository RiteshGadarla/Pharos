import pytest

from services.core.characterize.age import classify_age, with_age


def test_fresh_when_high_contrast_and_compact():
    band, reasoning = classify_age(contrast_db=-12.0, complexity_ratio=1.2)
    assert band == "fresh"
    assert "fresh" not in reasoning  # states the rule, doesn't just repeat the label
    assert "-12.0" in reasoning


def test_weathered_when_low_contrast_and_fragmented():
    band, reasoning = classify_age(contrast_db=-4.0, complexity_ratio=3.0)
    assert band == "weathered"
    assert reasoning


def test_intermediate_when_between_the_two_rules():
    band, reasoning = classify_age(contrast_db=-6.0, complexity_ratio=2.0)
    assert band == "intermediate"
    assert reasoning


def test_reasoning_never_mentions_hours():
    for contrast_db, complexity in [(-12.0, 1.2), (-4.0, 3.0), (-6.0, 2.0)]:
        _, reasoning = classify_age(contrast_db, complexity)
        assert "hour" not in reasoning.lower()


def test_with_age_builds_a_complete_slick_features_model():
    features = {
        "detection_id": "det-1",
        "area_km2": 0.5,
        "perimeter_km": 3.0,
        "complexity_ratio": 1.2,
        "major_axis_deg": 45.0,
        "elongation": 4.0,
        "mean_backscatter_db": -25.0,
        "contrast_db": -12.0,
    }
    result = with_age(features)
    assert result.age_band == "fresh"
    assert result.detection_id == "det-1"
    assert result.age_reasoning
