"""Tests for optical corroboration. See PLAN.md section 7.

Three honest states and no fourth. The state that matters most is
no_coverage, because it is the common one and because the temptation is
to dress it up as something else: SAR is the primary sensor precisely
because it works through cloud, at night and in any weather, so an
absent optical scene weakens nothing.
"""

from __future__ import annotations

import datetime

import numpy as np

from services.core.corroborate.optical import OpticalScene, corroborate
from services.core.schemas import Detection

T0 = datetime.datetime(2026, 1, 15, 2, 30)
CONFIG = {"window_hours": 6.0, "anomaly_threshold": 0.08}

DETECTION = Detection(
    detection_id="det-1",
    scene_id="S-1",
    class_name="oil",
    geometry={
        "type": "Polygon",
        "coordinates": [[[67.99, 16.99], [67.99, 17.01], [68.01, 17.01], [68.01, 16.99], [67.99, 16.99]]],
    },
    mean_class_prob=0.9,
    pixel_area=100,
)


def _scene(dark_patch: bool, hours_offset: float = 1.0, sensor: str = "Sentinel-2 L1C") -> OpticalScene:
    """A 100x100 reflectance grid over the detection's neighbourhood,
    optionally with a dark patch where the slick is.

    The scene bbox is twice the detection's in each direction, so the
    detection occupies the middle half of the grid (indices 25 to 75)
    and the surrounding sea reference ring is what is left. The dark
    patch has to cover that middle half, not a token square inside it,
    or the mean over the detection is dominated by clean water and the
    statistic correctly reports no anomaly."""
    reflectance = np.full((100, 100), 0.2, dtype=np.float32)
    if dark_patch:
        reflectance[25:76, 25:76] = 0.10
    return OpticalScene(
        sensor=sensor,
        acquired_at=T0 + datetime.timedelta(hours=hours_offset),
        bbox=(67.98, 16.98, 68.02, 17.02),
        reflectance=reflectance,
    )


def test_no_optical_scene_gives_no_coverage_and_says_why_sar_is_primary():
    result = corroborate(DETECTION, T0, [], CONFIG)
    assert result.status == "no_coverage"
    assert result.sensor is None
    assert "all weather" in result.reasoning or "any weather" in result.reasoning
    assert "cloud" in result.reasoning


def test_a_scene_outside_the_window_is_not_used():
    """An optical pass two days later says nothing about a slick's
    position at the SAR acquisition instant."""
    result = corroborate(DETECTION, T0, [_scene(dark_patch=True, hours_offset=48.0)], CONFIG)
    assert result.status == "no_coverage"


def test_a_dark_patch_where_the_slick_is_agrees():
    result = corroborate(DETECTION, T0, [_scene(dark_patch=True)], CONFIG)
    assert result.status == "agree"
    assert result.sensor == "Sentinel-2 L1C"
    assert result.delta_hours is not None


def test_featureless_water_where_the_slick_is_disagrees():
    result = corroborate(DETECTION, T0, [_scene(dark_patch=False)], CONFIG)
    assert result.status == "disagree"
    assert "below" in result.reasoning


def test_optical_never_claims_to_override_the_sar_detection():
    """The value of this stage is that the PS requirement is met and the
    reasoning is inspectable, not that optical decides anything."""
    for scene_list in ([], [_scene(True)], [_scene(False)]):
        result = corroborate(DETECTION, T0, scene_list, CONFIG)
        lowered = result.reasoning.lower()
        assert "override" not in lowered or "never overrides" in lowered


def test_the_closest_scene_in_time_wins():
    near = _scene(dark_patch=True, hours_offset=0.5, sensor="Sentinel-2 L1C")
    far = _scene(dark_patch=False, hours_offset=5.0, sensor="Sentinel-3 OLCI")
    result = corroborate(DETECTION, T0, [far, near], CONFIG)
    assert result.sensor == "Sentinel-2 L1C"
