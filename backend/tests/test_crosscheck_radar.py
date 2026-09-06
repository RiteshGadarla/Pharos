"""Tests for the SAR ship target cross check and factor F8.
See PLAN.md sections 11 and 12, and section 21's requirement:

  "A test that a vessel with a dark gap plus a corresponding unmatched
   radar target scores strictly higher than an identical vessel with the
   dark gap alone. This guards F8 and separates it from merely rewarding
   darkness."

That test is the point of this file. Without it, an engine that simply
added points for going dark would be indistinguishable from one that
requires an independent observation, and the difference is the whole
claim of section 11.
"""

from __future__ import annotations

import datetime

import numpy as np
import pytest
import xarray as xr
import yaml

from services.core.crosscheck.radar import match_confidence, match_targets_to_ais, run_cross_check
from services.core.schemas import AISPoint, AISTrack, DarkGap, ShipTarget, SlickFeatures
from services.core.scoring.engine import score_vessels

T0 = datetime.datetime(2026, 1, 15, 0, 0)
# The scene's acquisition instant, deliberately placed INSIDE the dark
# gaps _dark_vessel builds. A radar target is one observation at one
# moment, so it is only ever evidence about a vessel that was dark at
# that same moment: a gap that had already closed cannot explain a hull
# in the image. run_cross_check enforces that, so a fixture whose gap
# does not span acquisition would be testing nothing.
ACQUIRED_AT = T0 + datetime.timedelta(minutes=60)
RADAR_CONFIG = {"match_radius_m": 1500.0}


def _field() -> xr.Dataset:
    """A small field with one clear mass peak at (17.00, 68.00)."""
    lats = np.linspace(16.98, 17.02, 9)
    lons = np.linspace(67.98, 68.02, 9)
    times = np.array([T0 + datetime.timedelta(minutes=30 * i) for i in range(5)], dtype="datetime64[ns]")
    lat_grid, lon_grid = np.meshgrid(lats, lons, indexing="ij")
    blob = np.exp(-(((lat_grid - 17.0) / 0.01) ** 2 + ((lon_grid - 68.0) / 0.01) ** 2))
    field = np.tile(blob[None, :, :], (len(times), 1, 1))
    field = field / field.sum()
    return xr.Dataset(
        {"probability": (("time", "lat", "lon"), field)},
        coords={"time": times, "lat": lats, "lon": lons},
        attrs={"seed": 1, "n_members": 1, "kernel": "null"},
    )


def _envelope(lat: float, lon: float, half: float = 0.006) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon - half, lat - half],
                [lon - half, lat + half],
                [lon + half, lat + half],
                [lon + half, lat - half],
                [lon - half, lat - half],
            ]
        ],
    }


def _dark_vessel(mmsi: str, lat: float, lon: float) -> AISTrack:
    """A vessel that crosses (lat, lon) and goes dark right over it.

    Both vessels in the F8 test are built by this function, so they are
    identical in every respect the other seven factors can see. The only
    thing that differs between them is whether an unmatched radar target
    sits inside the envelope.
    """
    points = [
        AISPoint(ts=T0, lat=lat - 0.01, lon=lon - 0.01, sog=10.0, cog=45.0),
        AISPoint(ts=T0 + datetime.timedelta(minutes=30), lat=lat, lon=lon, sog=10.0, cog=45.0),
        AISPoint(ts=T0 + datetime.timedelta(minutes=120), lat=lat + 0.01, lon=lon + 0.01, sog=10.0, cog=45.0),
    ]
    gap = DarkGap(
        start=points[1].ts,
        end=points[2].ts,
        duration_min=90.0,
        entry_point=(points[1].lon, points[1].lat),
        exit_point=(points[2].lon, points[2].lat),
        envelope=_envelope(lat, lon),
    )
    return AISTrack(mmsi=mmsi, vessel_type="cargo", points=points, dark_gaps=[gap])


SLICK = SlickFeatures(
    detection_id="det-1", area_km2=1.0, perimeter_km=4.0, complexity_ratio=1.2,
    major_axis_deg=45.0, elongation=3.0, mean_backscatter_db=-25.0, contrast_db=-10.0,
    age_band="fresh", age_reasoning="test fixture",
)


def _scoring_config() -> dict:
    with open("config/scoring.yaml") as f:
        return yaml.safe_load(f)


def test_match_confidence_falls_off_linearly_to_the_radius():
    assert match_confidence(0.0, 1500.0) == pytest.approx(1.0)
    assert match_confidence(750.0, 1500.0) == pytest.approx(0.5)
    assert match_confidence(1500.0, 1500.0) == pytest.approx(0.0)
    assert match_confidence(3000.0, 1500.0) == pytest.approx(0.0)  # clamped, never negative


def test_a_target_on_a_broadcasting_vessel_is_matched():
    track = AISTrack(
        mmsi="419000010", vessel_type="cargo",
        points=[
            AISPoint(ts=T0, lat=17.0, lon=68.0, sog=10.0, cog=45.0),
            AISPoint(ts=T0 + datetime.timedelta(hours=2), lat=17.01, lon=68.01, sog=10.0, cog=45.0),
        ],
    )
    target = ShipTarget(
        target_id="t-1", scene_id="s", centroid=(68.0, 17.0), pixel_area=50, mean_backscatter_db=-4.0
    )
    resolved = match_targets_to_ais([target], [track], T0, 1500.0)
    assert resolved[0].matched_mmsi == "419000010"
    assert resolved[0].match_confidence > 0.9


def test_a_target_with_no_ais_nearby_stays_unmatched():
    track = AISTrack(
        mmsi="419000010", vessel_type="cargo",
        points=[
            AISPoint(ts=T0, lat=17.5, lon=68.5, sog=10.0, cog=45.0),
            AISPoint(ts=T0 + datetime.timedelta(hours=2), lat=17.51, lon=68.51, sog=10.0, cog=45.0),
        ],
    )
    target = ShipTarget(
        target_id="t-1", scene_id="s", centroid=(68.0, 17.0), pixel_area=50, mean_backscatter_db=-4.0
    )
    resolved = match_targets_to_ais([target], [track], T0, 1500.0)
    assert resolved[0].matched_mmsi is None


def test_one_ais_vessel_cannot_explain_two_targets():
    """Greedy assignment claims each MMSI once. Without this, a single
    broadcasting vessel would absorb a genuine unmatched target sitting
    beside it, which is exactly the finding this stage exists to make."""
    track = AISTrack(
        mmsi="419000010", vessel_type="cargo",
        points=[
            AISPoint(ts=T0, lat=17.0, lon=68.0, sog=10.0, cog=45.0),
            AISPoint(ts=T0 + datetime.timedelta(hours=2), lat=17.001, lon=68.001, sog=10.0, cog=45.0),
        ],
    )
    targets = [
        ShipTarget(target_id="t-1", scene_id="s", centroid=(68.0, 17.0), pixel_area=50, mean_backscatter_db=-4.0),
        ShipTarget(target_id="t-2", scene_id="s", centroid=(68.002, 17.002), pixel_area=50, mean_backscatter_db=-4.0),
    ]
    resolved = match_targets_to_ais(targets, [track], T0, 1500.0)
    matched = [t for t in resolved if t.matched_mmsi]
    assert len(matched) == 1


def test_a_dark_gap_with_a_radar_target_scores_strictly_higher_than_the_same_gap_alone():
    """PLAN.md section 21, the F8 guard.

    Two vessels, built identically, both dark over the field's peak.
    One has an unmatched radar target inside its envelope; the other
    does not. Everything the other seven factors can see is the same,
    so any score difference is F8 and nothing else.
    """
    field_ds = _field()
    with_radar = _dark_vessel("419000001", 17.0, 68.0)
    without_radar = _dark_vessel("419000002", 17.0, 68.0)

    # The unmatched target sits inside 419000001's envelope only. 419000002's
    # envelope is at the same place, so to keep the comparison honest the
    # two vessels are scored in separate runs against separate cross checks.
    unmatched = ShipTarget(
        target_id="t-unmatched", scene_id="s", centroid=(68.0, 17.0),
        pixel_area=64, mean_backscatter_db=-3.8,
    )
    config = _scoring_config()

    cross_with = run_cross_check([unmatched], [with_radar], field_ds, ACQUIRED_AT, RADAR_CONFIG)
    scores_with = score_vessels([with_radar], field_ds, SLICK, config, cross_check=cross_with)

    cross_without = run_cross_check([], [without_radar], field_ds, ACQUIRED_AT, RADAR_CONFIG)
    scores_without = score_vessels([without_radar], field_ds, SLICK, config, cross_check=cross_without)

    assert scores_with[0].factors["radar_confirmed_dark"] > 0
    assert scores_without[0].factors["radar_confirmed_dark"] == 0
    assert scores_with[0].total > scores_without[0].total
    assert scores_with[0].radar_support == "t-unmatched"
    assert scores_without[0].radar_support is None


def test_a_gap_that_closed_before_acquisition_cannot_claim_the_target():
    """A dead-reckoned envelope widens at the vessel's plausible maximum
    speed, so after an hour it is larger than the whole origin field.
    Without the acquisition-instant rule, any vessel that had ever gone
    dark nearby would absorb the target, and F8 would stop
    discriminating between them."""
    field_ds = _field()
    vessel = _dark_vessel("419000001", 17.0, 68.0)
    unmatched = ShipTarget(
        target_id="t-unmatched", scene_id="s", centroid=(68.0, 17.0),
        pixel_area=64, mean_backscatter_db=-3.8,
    )
    # Acquisition after the gap closed at T0 + 120 minutes.
    late = T0 + datetime.timedelta(minutes=200)
    cross = run_cross_check([unmatched], [vessel], field_ds, late, RADAR_CONFIG)
    assert cross.envelope_hits["t-unmatched"] == []


def test_f8_does_not_fire_for_a_dark_gap_far_from_any_unmatched_target():
    """The discrimination this factor has to have. A vessel that goes
    dark somewhere else entirely gets nothing from F8, however dark it
    went."""
    field_ds = _field()
    near = _dark_vessel("419000001", 17.0, 68.0)
    far = _dark_vessel("419000002", 17.02, 68.02)
    unmatched = ShipTarget(
        target_id="t-unmatched", scene_id="s", centroid=(68.0, 17.0),
        pixel_area=64, mean_backscatter_db=-3.8,
    )
    cross = run_cross_check([unmatched], [near, far], field_ds, ACQUIRED_AT, RADAR_CONFIG)
    assert "419000001" in cross.envelope_hits["t-unmatched"]
    assert "419000002" not in cross.envelope_hits["t-unmatched"]
