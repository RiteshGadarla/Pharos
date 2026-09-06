"""Age band to origin time window. See PLAN.md sections 8 and 12.

The backward field answers "where could this oil have come from, at
every hour of the horizon". On its own it treats an origin 48 hours ago
as exactly as plausible as one an hour ago, and it has no way not to:
the drift physics does not know when the discharge happened.

The slick's own characterisation does carry that information, weakly.
Oil spreads and its contrast against the sea falls as it weathers, so a
compact high-contrast slick has spent less time on the surface than a
fragmented low-contrast one. `characterize/age.py` already turns that
into a relative band with stated reasoning. Until this module existed
the band went to the dossier and the UI and stopped there, never
reaching the scoring engine, which meant the only evidence in the whole
system about *when* the discharge happened was decorative.

This module turns the band into a weight over the field's time axis,
which F1 and F2 apply to each timestep's contribution.

Three rules keep it honest.

It is a band, never a point. PLAN.md's non-goals rule out absolute slick
age in hours, and nothing here recovers it. The windows are wide, they
overlap, and they come from config so they can be argued with.

It tapers, it does not cut off. The boundary between a compact slick and
a spreading one is not sharp, and scoring it as though it were would
claim precision the radiometry cannot support.

It downweights, it never eliminates. The weight bottoms out at
`floor_weight`, not at zero, for the same reason F6 (vessel
plausibility) is capped: a heuristic prior must not be able to clear a
vessel on its own. A vessel in the origin field at an implausible time
scores lower. It does not disappear.
"""

from __future__ import annotations

import datetime

import numpy as np

DEFAULT_BANDS: dict[str, tuple[float, float]] = {
    "fresh": (0.0, 12.0),
    "intermediate": (6.0, 30.0),
    "weathered": (24.0, 48.0),
}
DEFAULT_TAPER_HOURS = 6.0
DEFAULT_FLOOR_WEIGHT = 0.15

# What an unrecognised band gets: the full horizon at full weight, which
# is the behaviour before this module existed. An age band nobody
# configured is missing evidence, and missing evidence must leave the
# scoring exactly as it found it rather than quietly reshaping it.
NEUTRAL_WINDOW = (0.0, float("inf"))


def window_for_band(age_band: str, config: dict | None = None) -> tuple[float, float]:
    """The [earliest, latest] hours before acquisition in which a slick
    of this band plausibly originated."""
    cfg = config or {}
    bands = cfg.get("bands") or DEFAULT_BANDS
    if age_band not in bands:
        return NEUTRAL_WINDOW
    lo, hi = bands[age_band]
    return float(lo), float(hi)


def weight_at_lag(lag_hours: float, window: tuple[float, float], config: dict | None = None) -> float:
    """Weight in [floor, 1] for a timestep `lag_hours` before acquisition.

    1.0 inside the window, falling linearly to the floor across
    `taper_hours` on each side, and the floor beyond that.
    """
    cfg = config or {}
    taper = float(cfg.get("taper_hours", DEFAULT_TAPER_HOURS))
    floor = float(cfg.get("floor_weight", DEFAULT_FLOOR_WEIGHT))
    lo, hi = window

    if lo <= lag_hours <= hi:
        return 1.0
    distance = (lo - lag_hours) if lag_hours < lo else (lag_hours - hi)
    if taper <= 0 or distance >= taper:
        return floor
    # Linear from 1 at the window edge to the floor a full taper out.
    return float(1.0 - (1.0 - floor) * (distance / taper))


def field_time_weights(
    field_times: list[datetime.datetime],
    acquired_at: datetime.datetime,
    age_band: str,
    config: dict | None = None,
) -> dict[datetime.datetime, float]:
    """Weight per field timestep, keyed by the timestep itself.

    A dict rather than an array so callers cannot silently pair the
    weights with the wrong timesteps: F1 and F2 iterate the field's
    times in their own order, and an index-aligned array would let a
    reordering shift every vessel's score with nothing to catch it.
    """
    window = window_for_band(age_band, config)
    weights: dict[datetime.datetime, float] = {}
    for t in field_times:
        lag = (acquired_at - t).total_seconds() / 3600.0
        # A timestep after acquisition is not an origin at all. It is
        # the half bin the gridding adds past the last sample, so it
        # sits at the window's near edge rather than being extrapolated
        # to a negative lag the taper was never meant to see.
        weights[t] = weight_at_lag(max(0.0, lag), window, config)
    return weights


def describe_window(age_band: str, config: dict | None = None) -> str:
    """One line for the UI and the dossier, stating the window and that
    it is a band rather than an estimate of age."""
    lo, hi = window_for_band(age_band, config)
    if hi == float("inf"):
        return (
            f"Age band {age_band!r} has no configured origin window, so every hour of the "
            "backward horizon is weighted equally."
        )
    return (
        f"A {age_band} slick is taken to have originated between {lo:.0f} and {hi:.0f} hours "
        "before acquisition. This is a band derived from the slick's contrast and complexity, "
        "not an estimate of its age in hours, which a single SAR acquisition cannot support. "
        "Timesteps outside the band are downweighted, never excluded."
    )


def weighted_span_hours(weights: dict[datetime.datetime, float]) -> float:
    """Total weight expressed as hours, for reporting how much of the
    horizon the age band actually favours."""
    if not weights:
        return 0.0
    return float(np.sum(list(weights.values())))
