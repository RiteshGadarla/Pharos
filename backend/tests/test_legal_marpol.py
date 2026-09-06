"""Tests for the MARPOL Annex I layer. See PLAN.md sections 13 and 21:

  "A test that MarpolAssessment.est_discharge_l_per_nm is a band and
   never a scalar."

The schema enforces the band, and the tests below enforce the harder
rule around it: this layer never concludes that a discharge was
permitted on a basis it cannot observe, and it never collapses "not
evaluated" into "no".
"""

from __future__ import annotations

import datetime

import numpy as np
import pytest
import xarray as xr
import yaml
from pydantic import ValidationError

from services.core.legal.marpol import StaticLayers, assess, discharge_band_l_per_nm
from services.core.schemas import AISPoint, AISTrack, MarpolAssessment, SlickFeatures

T0 = datetime.datetime(2026, 1, 15, 0, 0)

SLICK = SlickFeatures(
    detection_id="det-1", area_km2=2.0, perimeter_km=8.0, complexity_ratio=1.3,
    major_axis_deg=45.0, elongation=4.0, mean_backscatter_db=-25.0, contrast_db=-10.0,
    age_band="fresh", age_reasoning="test fixture",
)


def _marpol_config() -> dict:
    with open("config/marpol.yaml") as f:
        return yaml.safe_load(f)


def _field() -> xr.Dataset:
    lats = np.linspace(16.98, 17.02, 5)
    lons = np.linspace(67.98, 68.02, 5)
    times = np.array([T0 + datetime.timedelta(minutes=30 * i) for i in range(5)], dtype="datetime64[ns]")
    field = np.ones((len(times), len(lats), len(lons)))
    field = field / field.sum()
    return xr.Dataset(
        {"probability": (("time", "lat", "lon"), field)},
        coords={"time": times, "lat": lats, "lon": lons},
        attrs={"seed": 1, "n_members": 1},
    )


def _track(mmsi: str, vessel_type: str, sog: float) -> AISTrack:
    return AISTrack(
        mmsi=mmsi,
        vessel_type=vessel_type,
        points=[
            AISPoint(ts=T0 + datetime.timedelta(minutes=30 * i), lat=17.0 + 0.002 * i, lon=68.0 + 0.002 * i, sog=sog, cog=45.0)
            for i in range(5)
        ],
    )


def test_the_discharge_estimate_is_a_band():
    band = discharge_band_l_per_nm(SLICK, track_nm=10.0, thickness_band_um=(0.3, 5.0))
    assert band is not None
    low, high = band
    assert high > low > 0


def test_the_schema_rejects_a_scalar_disguised_as_a_band():
    """The schema is the enforcement point, so it gets its own test:
    a reversed or malformed band must not construct at all."""
    with pytest.raises(ValidationError):
        MarpolAssessment(mmsi="1", est_discharge_l_per_nm=(500.0, 10.0), flag="conditions_not_met")


def test_a_slow_vessel_fails_the_en_route_condition():
    config = _marpol_config()
    assessment = assess(_track("419000001", "cargo", sog=1.0), _field(), SLICK, config)
    assert assessment.en_route is False
    assert assessment.flag == "conditions_not_met"
    assert any("en route" in a for a in assessment.assumptions)


def test_unmeasured_conditions_are_not_evaluated_rather_than_satisfied():
    """The failure that would matter most: reporting an unmeasured
    distance to land as if the vessel had cleared the limit."""
    config = _marpol_config()
    empty_layers = StaticLayers(coastline=[], special_areas=[])
    assessment = assess(_track("419000001", "cargo", sog=10.0), _field(), SLICK, config, layers=empty_layers)
    assert assessment.distance_to_land_nm is None
    assert assessment.in_special_area is None
    assert assessment.flag == "insufficient_data"


def test_the_ppm_condition_is_always_declared_unevaluated():
    """Oil content in parts per million is not observable from
    satellite. Every assessment must say so, whatever it concludes,
    because it is the condition that would otherwise let this layer be
    read as a finding of legality."""
    config = _marpol_config()
    for sog in (1.0, 10.0):
        assessment = assess(_track("419000001", "tanker", sog=sog), _field(), SLICK, config)
        assert any("parts per million" in a for a in assessment.assumptions)


def test_assumptions_are_never_empty():
    """They are printed verbatim in the dossier. An assessment with no
    assumptions attached would read as a bare verdict, which is exactly
    what this layer must not produce."""
    config = _marpol_config()
    assessment = assess(_track("419000001", "tanker", sog=10.0), _field(), SLICK, config)
    assert assessment.assumptions


def test_a_track_outside_the_window_yields_insufficient_data():
    config = _marpol_config()
    away = AISTrack(
        mmsi="419000009", vessel_type="cargo",
        points=[
            AISPoint(ts=T0 + datetime.timedelta(days=5), lat=17.0, lon=68.0, sog=10.0, cog=45.0),
            AISPoint(ts=T0 + datetime.timedelta(days=5, hours=1), lat=17.01, lon=68.01, sog=10.0, cog=45.0),
        ],
    )
    assessment = assess(away, _field(), SLICK, config)
    assert assessment.flag == "insufficient_data"
