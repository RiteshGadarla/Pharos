"""The age band has to actually move the score, or it is decoration.

The unit tests in test_age_origin_window.py check the weighting
function. This one checks that it reaches the ranking: two identical
vessels that differ only in WHEN they were in the origin field must
score differently, and which of them wins must follow the slick's
condition rather than being fixed.

That is the whole reason for the feature. Before it, the only evidence
the system held about when the discharge happened was computed, printed
in the dossier, drawn in the UI and then ignored by the engine.
"""

import datetime

import numpy as np
import pytest
import xarray as xr

from services.core.schemas import AISPoint, AISTrack, SlickFeatures
from services.core.scoring.factors import compute_field_integral
from services.core.scoring.age_window import field_time_weights

ACQUIRED_AT = datetime.datetime(2026, 1, 15, 2, 30)

CONFIG = {
    "bands": {"fresh": [0, 12], "intermediate": [6, 30], "weathered": [24, 48]},
    "taper_hours": 6.0,
    "floor_weight": 0.15,
}


def _field() -> xr.Dataset:
    """A field with equal mass at every hour of a 48 hour horizon, in
    one cell that drifts steadily away from the slick.

    Flat in time on purpose: any difference the age band produces is
    then attributable to the weighting alone, not to the field being
    denser near acquisition (which the real field is, and which would
    mask the effect being tested).
    """
    hours = list(range(48, -1, -1))  # 48 hours back to acquisition
    times = [ACQUIRED_AT - datetime.timedelta(hours=h) for h in hours]
    lats = np.round(np.arange(17.00, 17.50, 0.01), 3)
    lons = np.round(np.arange(68.00, 68.50, 0.01), 3)

    grid = np.zeros((len(times), len(lats), len(lons)))
    # One hot cell per timestep, marching north as time runs backwards.
    for i, h in enumerate(hours):
        grid[i, h % len(lats), h % len(lons)] = 1.0
    grid /= grid.sum()

    return xr.Dataset(
        {"probability": (("time", "lat", "lon"), grid)},
        coords={"time": np.array(times, dtype="datetime64[ns]"), "lat": lats, "lon": lons},
        attrs={"direction": "backward"},
    )


def _vessel_sitting_at(field_ds: xr.Dataset, lag_hours_range: tuple[int, int]) -> AISTrack:
    """A vessel parked on the field's hot cell for a span of hours, and
    nowhere near it otherwise."""
    lo, hi = lag_hours_range
    lats = field_ds["lat"].values
    lons = field_ds["lon"].values
    points = []
    for h in range(50, -1, -1):
        t = ACQUIRED_AT - datetime.timedelta(hours=h)
        if lo <= h <= hi:
            lat, lon = float(lats[h % len(lats)]), float(lons[h % len(lons)])
        else:
            lat, lon = 17.49, 68.49  # a corner the hot cell never visits
        points.append(AISPoint(ts=t, lat=lat, lon=lon, sog=8.0, cog=90.0, heading=90.0))
    return AISTrack(mmsi="000000000", vessel_type="tanker", points=points, dark_gaps=[], integrity_flags=[])


def _integral(track: AISTrack, field_ds: xr.Dataset, band: str | None) -> float:
    weights = (
        None
        if band is None
        else field_time_weights(
            [np.datetime64(t).astype("datetime64[us]").astype(datetime.datetime) for t in field_ds["time"].values],
            ACQUIRED_AT,
            band,
            CONFIG,
        )
    )
    return compute_field_integral(track, field_ds, weights)


def test_a_fresh_slick_favours_the_vessel_that_was_there_recently():
    field_ds = _field()
    recent = _vessel_sitting_at(field_ds, (2, 8))
    long_ago = _vessel_sitting_at(field_ds, (36, 42))

    assert _integral(recent, field_ds, "fresh") > _integral(long_ago, field_ds, "fresh")


def test_a_weathered_slick_favours_the_vessel_that_was_there_long_ago():
    """The inverse must hold on the same two vessels and the same field.
    If it does not, the weighting is a recency prior rather than
    evidence read off the slick."""
    field_ds = _field()
    recent = _vessel_sitting_at(field_ds, (2, 8))
    long_ago = _vessel_sitting_at(field_ds, (36, 42))

    assert _integral(long_ago, field_ds, "weathered") > _integral(recent, field_ds, "weathered")


def test_without_the_age_band_the_two_vessels_are_indistinguishable():
    """The state before this feature: identical behaviour at different
    times scored the same, so the ranking could not use timing at all."""
    field_ds = _field()
    recent = _vessel_sitting_at(field_ds, (2, 8))
    long_ago = _vessel_sitting_at(field_ds, (36, 42))

    assert _integral(recent, field_ds, None) == pytest.approx(_integral(long_ago, field_ds, None), rel=1e-9)


def test_the_age_band_downweights_but_never_zeroes_a_vessel():
    """A vessel in the origin field at an implausible time must still
    carry a score. The band is heuristic and must not be able to clear
    anyone on its own."""
    field_ds = _field()
    long_ago = _vessel_sitting_at(field_ds, (36, 42))

    penalised = _integral(long_ago, field_ds, "fresh")
    unweighted = _integral(long_ago, field_ds, None)

    assert 0.0 < penalised < unweighted
    assert penalised >= unweighted * CONFIG["floor_weight"] * 0.99
