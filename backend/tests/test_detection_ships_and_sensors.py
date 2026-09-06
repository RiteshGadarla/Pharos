"""Tests for ship target extraction and the sensor adapters.
See PLAN.md sections 5A and 11.

The EOS-04 adapter test is the unusual one: it asserts that a stub
raises. That is deliberate. The gap between "claims sensor agnosticism"
and "demonstrates it" is exactly this, an adapter that either works or
says clearly that it does not, rather than one that silently returns
something plausible.
"""

from __future__ import annotations

import datetime

import numpy as np
import pytest
from affine import Affine

from services.detection.sensors import EOS04Adapter, Sentinel1Adapter, get_adapter
from services.detection.ships import extract_ship_targets, targets_to_feature_collection

CLASSES = ["background", "oil_spill", "ships", "look_alike", "wakes"]
# A metre-based transform in a UTM-like projected CRS, 10 m pixels.
TRANSFORM = Affine(10.0, 0.0, 500000.0, 0.0, -10.0, 1900000.0)
SRC_CRS = "EPSG:32643"


def _softmax_with_ships(blobs: list[tuple[int, int, int]]) -> np.ndarray:
    """A 200x200 softmax field that is background everywhere except for
    the given (row, col, half_size) ship blobs."""
    softmax = np.zeros((200, 200, len(CLASSES)), dtype=np.float32)
    softmax[..., 0] = 0.9  # background
    ships_index = CLASSES.index("ships")
    for row, col, half in blobs:
        softmax[row - half : row + half, col - half : col + half, 0] = 0.05
        softmax[row - half : row + half, col - half : col + half, ships_index] = 0.95
    return softmax


def test_a_scene_with_no_ships_yields_no_targets():
    softmax = np.zeros((50, 50, len(CLASSES)), dtype=np.float32)
    softmax[..., 0] = 1.0
    assert extract_ship_targets(softmax, TRANSFORM, SRC_CRS, CLASSES, "S-1") == []


def test_each_connected_component_becomes_one_target():
    softmax = _softmax_with_ships([(50, 50, 3), (150, 150, 3)])
    targets = extract_ship_targets(softmax, TRANSFORM, SRC_CRS, CLASSES, "S-1")
    assert len(targets) == 2
    assert {t.target_id for t in targets} == {"S-1-ship-000", "S-1-ship-001"}


def test_speckle_below_the_minimum_area_is_rejected():
    """Speckle is the dominant false positive at C-band, and a cross
    check flooded with one-pixel targets reports a fleet of dark vessels
    that does not exist."""
    softmax = _softmax_with_ships([(50, 50, 1), (150, 150, 4)])  # 4 px and 64 px
    targets = extract_ship_targets(softmax, TRANSFORM, SRC_CRS, CLASSES, "S-1", min_pixel_area=16)
    assert len(targets) == 1
    assert targets[0].pixel_area == 64


def test_an_implausibly_large_component_is_rejected():
    """The other failure mode: mis-segmented land or a slick edge picked
    up as one enormous hull."""
    softmax = _softmax_with_ships([(100, 100, 60)])
    targets = extract_ship_targets(softmax, TRANSFORM, SRC_CRS, CLASSES, "S-1", max_pixel_area=1000)
    assert targets == []


def test_targets_are_georeferenced_to_lon_lat():
    softmax = _softmax_with_ships([(50, 50, 3)])
    targets = extract_ship_targets(softmax, TRANSFORM, SRC_CRS, CLASSES, "S-1")
    lon, lat = targets[0].centroid
    assert 60.0 < lon < 100.0  # somewhere sensible in UTM zone 43N's range
    assert 0.0 < lat < 30.0


def test_mean_backscatter_is_carried_when_the_image_is_given():
    """So the dossier can report unmatched target sizes and
    brightnesses, not just a count."""
    softmax = _softmax_with_ships([(50, 50, 3)])
    backscatter = np.full((200, 200), -22.0, dtype=np.float32)
    backscatter[47:53, 47:53] = -3.0
    targets = extract_ship_targets(
        softmax, TRANSFORM, SRC_CRS, CLASSES, "S-1", backscatter_db=backscatter
    )
    assert targets[0].mean_backscatter_db == pytest.approx(-3.0)


def test_feature_collection_carries_the_match_state():
    softmax = _softmax_with_ships([(50, 50, 3)])
    targets = extract_ship_targets(softmax, TRANSFORM, SRC_CRS, CLASSES, "S-1")
    collection = targets_to_feature_collection(targets)
    assert collection["type"] == "FeatureCollection"
    assert collection["features"][0]["properties"]["matched_mmsi"] is None


def test_the_sentinel1_adapter_reads_the_fixture_scene():
    adapter = Sentinel1Adapter()
    db, transform, crs = adapter.read_backscatter_db("data/fixtures/synthetic_scene.tif")
    assert db.ndim == 2
    assert np.isfinite(db).any()
    meta = adapter.read_metadata(
        "data/fixtures/synthetic_scene.tif", "S-1", datetime.datetime(2026, 1, 15, 2, 30)
    )
    assert meta.sensor == "S1"
    assert meta.bbox[0] < meta.bbox[2] and meta.bbox[1] < meta.bbox[3]


def test_the_eos04_adapter_raises_rather_than_pretending():
    """A stub that returned something plausible would be worse than no
    stub at all: it would let a claim of multi-sensor support pass
    unchallenged."""
    adapter = EOS04Adapter()
    with pytest.raises(NotImplementedError, match="documented stub"):
        adapter.read_backscatter_db("anything.tif")
    with pytest.raises(NotImplementedError):
        adapter.read_metadata("anything.tif", "S-1", datetime.datetime(2026, 1, 15))


def test_adapter_selection_comes_from_config():
    assert get_adapter("sentinel1").name == "S1"
    assert get_adapter("EOS04").name == "EOS04"
    with pytest.raises(ValueError, match="unknown sensor"):
        get_adapter("hyperspectral-imaginary")
