"""Tests for the wind physics gate. See PLAN.md section 6 and 16
("every detection carries a verdict and a reason")."""

import numpy as np
import pytest
import yaml

from services.core.gate.wind import gate_detections, gate_one, load_wind_field
from services.core.schemas import Detection

WIND_FIXTURE = "data/fixtures/synthetic_wind.nc"
ACQUIRED_AT = np.datetime64("2026-01-15T02:30:00")


@pytest.fixture(scope="module")
def wind_config():
    with open("config/pipeline.yaml") as f:
        return yaml.safe_load(f)["wind_gate"]


@pytest.fixture(scope="module")
def wind_ds():
    return load_wind_field(WIND_FIXTURE)


def _square_detection(detection_id: str, center_lon: float, center_lat: float, half=0.01) -> Detection:
    coords = [
        [center_lon - half, center_lat - half],
        [center_lon - half, center_lat + half],
        [center_lon + half, center_lat + half],
        [center_lon + half, center_lat - half],
        [center_lon - half, center_lat - half],
    ]
    return Detection(
        detection_id=detection_id,
        scene_id="FIXTURE-001",
        class_name="oil",
        geometry={"type": "Polygon", "coordinates": [coords]},
        mean_class_prob=0.8,
        pixel_area=1000,
    )


@pytest.mark.parametrize(
    "lon,expected_verdict",
    [
        (72.2, "suppress"),  # 1.5 m/s, below wind_min
        (72.7, "downgrade"),  # 3.0 m/s, within margin
        (73.0, "accept"),  # 6.0 m/s, valid window
        (73.4, "suppress"),  # 13.0 m/s, above wind_max
    ],
)
def test_gate_verdict_by_wind_zone(wind_ds, wind_config, lon, expected_verdict):
    det = _square_detection("det-1", lon, 19.5)
    result = gate_detections([det], wind_ds, ACQUIRED_AT, wind_config)[0]
    assert result.verdict == expected_verdict
    assert result.reason  # non-empty, per the contract


def test_gate_never_drops_a_detection(wind_ds, wind_config):
    dets = [
        _square_detection("low", 72.2, 19.5),
        _square_detection("mid", 72.7, 19.5),
        _square_detection("ok", 73.0, 19.5),
        _square_detection("high", 73.4, 19.5),
    ]
    results = gate_detections(dets, wind_ds, ACQUIRED_AT, wind_config)
    assert len(results) == len(dets)
    assert {r.detection_id for r in results} == {d.detection_id for d in dets}


def test_gate_one_boundary_at_exactly_wind_min_falls_in_downgrade_band():
    config = {"wind_min_ms": 2.5, "wind_max_ms": 11.0, "downgrade_margin_ms": 1.0}
    det = _square_detection("det-1", 72.7, 19.5)
    # exactly at wind_min: not < wind_min, so falls through to the
    # downgrade band (<= wind_min + margin), not suppressed
    result = gate_one(det, wind_speed_ms=2.5, config=config)
    assert result.verdict == "downgrade"


def test_gate_one_boundary_at_exactly_wind_max_is_accepted():
    config = {"wind_min_ms": 2.5, "wind_max_ms": 11.0, "downgrade_margin_ms": 1.0}
    det = _square_detection("det-1", 72.7, 19.5)
    result = gate_one(det, wind_speed_ms=11.0, config=config)
    assert result.verdict == "accept"


def test_every_gate_result_has_a_reason(wind_ds, wind_config):
    dets = [
        _square_detection("low", 72.2, 19.5),
        _square_detection("mid", 72.7, 19.5),
        _square_detection("ok", 73.0, 19.5),
        _square_detection("high", 73.4, 19.5),
    ]
    results = gate_detections(dets, wind_ds, ACQUIRED_AT, wind_config)
    for r in results:
        assert isinstance(r.reason, str)
        assert len(r.reason) > 0
