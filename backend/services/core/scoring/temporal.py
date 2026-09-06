"""F9, temporal consistency: was the vessel there at a plausible HOUR?

See PLAN.md sections 8 and 12.

scoring/age_window.py already turns the slick's age band into a weight
over the field's time axis, which F1 and F2 apply to each timestep's
contribution. That weighting asks an integrated question: how much of
this vessel's probability mass sits at plausible hours. The answer is
entangled with space, because a vessel with a lot of mass at the wrong
time can integrate to the same number as one with a little mass at
exactly the right time.

This module asks the timing question on its own. For each vessel it
finds the single hour at which that vessel had its best opportunity to
be the source, and scores how far that hour sits outside the window the
slick's own condition implies. Space is marginalised out: two vessels
whose opportunity peaked at the same hour score identically here no
matter how much mass either of them had.

The point of separating it is that it can be shown. Timing used to be
invisible, buried inside F1's integral, and a room cannot interrogate a
weight it never sees. As its own factor it becomes its own step in the
case build, with its own bar, that a jury can watch move the ranking.

THE BAND EDGE IS NOT A CLIFF
----------------------------
The window is an estimate, so its edges are estimates too. If the real
discharge happened 14 hours ago and the slick's contrast puts the band
at 0 to 12 hours, then every vessel that passed in those two extra
hours is a live candidate and the scoring must not quietly bury them.
That is not a tolerance to be generous about, it is the ordinary case:
the band comes from radiometry, and radiometry does not resolve a two
hour difference.

So the penalty does not start at the band edge. It starts
`band_uncertainty_hours` beyond it, and only then begins to bite. Inside
that margin a vessel scores exactly as though it were inside the band,
because on the evidence available it may well be.

THE CURVE
---------
Beyond the margin the score falls as a Gaussian in the remaining
offset, and scoring/engine.py runs it through the same logit as every
other soft factor. That composition is where the non-linearity lives:
a couple of hours past the margin costs little, the middle of the range
is steep, and past about 24 hours it saturates.

It saturates deliberately. engine.py's own docstring records that
unbounded single-factor penalties were a bug in this codebase once
already: LOGIT_EPS used to be 1e-6, one factor could move the total by
13.8, and "no evidence here" outranked "clear evidence there". F9
bottoms out at the same floor every other soft factor obeys, and how
much that floor is worth is set by its weight in config, not by an
unbounded logarithm.

WHAT IT MUST NOT DO
-------------------
It must not eliminate. The age band is heuristic, derived from contrast
and complexity, and age_window.py states three times over that it
downweights and never clears a vessel. The same rule binds here and for
the same reason it binds F6: a weak prior that can convict on its own
is not a prior, it is a verdict.
"""

from __future__ import annotations

import datetime

import numpy as np
import xarray as xr

from services.core.ais.tracks import position_at
from services.core.schemas import AISTrack
from services.core.scoring.age_window import window_for_band

# Score at a perfectly consistent time, and at an arbitrarily
# inconsistent one. These are the logit clamp in engine.py, 0.05 and
# 0.95, on purpose: the curve should be able to reach the bounds the
# engine already imposes rather than saturating somewhere short of them
# and quietly capping F9 below every other factor's range.
PEAK_SCORE = 0.95
FLOOR_SCORE = 0.05

# How far past the band edge a vessel still scores as if it were inside.
# See the module docstring: the band is an estimate and its edges are
# estimates, so a discharge a couple of hours outside is not a different
# kind of event, it is the same event and a slightly wrong band.
DEFAULT_BAND_UNCERTAINTY_HOURS = 3.0

# Gaussian scale of the falloff BEYOND the uncertainty margin, in hours.
DEFAULT_FALLOFF_HOURS = 8.0

# Returned when the timing question cannot be asked at all: no age band,
# no acquisition time, or a vessel with no position anywhere in the
# field. Must be 0.5 so that logit(0.5) is 0 and absent evidence adds
# nothing either way. See factors.NEUTRAL_FACTOR.
NEUTRAL_SCORE = 0.5


def _config(config: dict | None) -> tuple[float, float]:
    cfg = config or {}
    return (
        float(cfg.get("band_uncertainty_hours", DEFAULT_BAND_UNCERTAINTY_HOURS)),
        float(cfg.get("falloff_hours", DEFAULT_FALLOFF_HOURS)),
    )


def opportunity_time(
    track: AISTrack, field_ds: xr.Dataset
) -> tuple[datetime.datetime | None, float]:
    """The hour at which this vessel had its best opportunity to be the
    source, and how close to that hour's most likely origin it was, as a
    fraction in [0, 1].

    Read off the UNWEIGHTED field on purpose. Sampling the age-weighted
    field would find the peak the age band had already decided it wanted
    to find, and F9 would then be scoring its own assumption. The
    weighting belongs downstream, in the comparison against the window,
    where it can be seen.

    THE PROBABILITY IS NORMALISED PER TIMESTEP, AND IT HAS TO BE
    ---------------------------------------------------------
    The obvious implementation takes the argmax of raw P along the
    track. It is wrong, and it fails quietly, which is worse.

    The field's mass is not spread evenly over time: it concentrates
    around the hours the drift makes plausible, so some timesteps hold
    orders of magnitude more probability than others. Take a raw argmax
    and every vessel's answer collapses onto whichever timestep is
    densest, because that slice dominates the comparison no matter
    where any particular vessel was. The first version of this module
    did exactly that, and all three survivors of the demo case came back
    peaking within half an hour of each other with identical scores:
    the factor was measuring the FIELD's peak hour and reporting it as
    the VESSEL's.

    Dividing by each timestep's own maximum asks the question that was
    actually intended: at this hour, how close was this vessel to the
    best place it could have been? That is a fraction in [0, 1] which
    means the same thing at every hour, so the argmax over it finds the
    hour the vessel was best aligned with the field rather than the hour
    the field happened to be busiest.
    """
    times = [_as_datetime(t) for t in field_ds["time"].values]
    prob = field_ds["probability"]
    best_t: datetime.datetime | None = None
    best_rel = 0.0
    for t in times:
        pos = position_at(track, t)
        if pos is None:
            continue
        lat, lon = pos
        slice_t = prob.sel(time=t, method="nearest")
        slice_peak = float(np.max(slice_t.values))
        if slice_peak <= 0.0:
            continue
        p = float(slice_t.sel(lat=lat, lon=lon, method="nearest").values)
        rel = p / slice_peak
        if rel > best_rel:
            best_rel, best_t = rel, t
    return best_t, best_rel


def offset_from_window(
    lag_hours: float, window: tuple[float, float], config: dict | None = None
) -> float:
    """Hours by which `lag_hours` misses the window, AFTER the
    uncertainty margin is allowed for.

    Zero inside the window and zero anywhere within the margin of it,
    which is the whole point: a vessel two hours outside a band whose
    edge is itself uncertain by three has not been shown to be at the
    wrong time at all.
    """
    uncertainty, _ = _config(config)
    lo, hi = window
    if lo <= lag_hours <= hi:
        return 0.0
    raw = (lo - lag_hours) if lag_hours < lo else (lag_hours - hi)
    return float(max(0.0, raw - uncertainty))


def score_from_offset(offset_hours: float, config: dict | None = None) -> float:
    """The curve itself, exposed separately so its shape can be tested
    without building a vessel and a field to get at it."""
    _, falloff = _config(config)
    if falloff <= 0:
        return PEAK_SCORE if offset_hours <= 0 else FLOOR_SCORE
    decay = float(np.exp(-((max(0.0, offset_hours) / falloff) ** 2)))
    return float(FLOOR_SCORE + (PEAK_SCORE - FLOOR_SCORE) * decay)


def compute_temporal_consistency(
    track: AISTrack,
    field_ds: xr.Dataset,
    age_band: str | None,
    acquired_at: datetime.datetime | None,
    window_config: dict | None = None,
    config: dict | None = None,
) -> float:
    """F9 in [FLOOR_SCORE, PEAK_SCORE], or NEUTRAL_SCORE when the
    question cannot be asked."""
    if age_band is None or acquired_at is None:
        return NEUTRAL_SCORE
    window = window_for_band(age_band, window_config)
    if window[1] == float("inf"):
        # An unconfigured band is missing evidence, not evidence of a
        # wide window. Leave the ranking exactly as it was found.
        return NEUTRAL_SCORE

    t_star, alignment = opportunity_time(track, field_ds)
    if t_star is None or alignment <= 0.0:
        return NEUTRAL_SCORE

    lag = (acquired_at - t_star).total_seconds() / 3600.0
    return score_from_offset(offset_from_window(max(0.0, lag), window, config), config)


def describe_timing(
    track: AISTrack,
    field_ds: xr.Dataset,
    age_band: str | None,
    acquired_at: datetime.datetime | None,
    window_config: dict | None = None,
    config: dict | None = None,
) -> dict:
    """Everything the UI and the dossier need to explain one vessel's
    F9 in words, rather than showing a bar and asking for trust."""
    uncertainty, _ = _config(config)
    t_star, alignment = opportunity_time(track, field_ds)
    out: dict = {
        "mmsi": track.mmsi,
        "opportunity_at": t_star.isoformat() if t_star else None,
        "opportunity_alignment": alignment,
        "lag_hours": None,
        "offset_hours": None,
        "within_band": None,
        "within_uncertainty": None,
        "score": NEUTRAL_SCORE,
        "statement": "",
    }
    if age_band is None or acquired_at is None or t_star is None or alignment <= 0.0:
        out["statement"] = (
            "No timing evidence for this vessel: it is scored neutrally on when it was there."
        )
        return out

    window = window_for_band(age_band, window_config)
    lag = max(0.0, (acquired_at - t_star).total_seconds() / 3600.0)
    lo, hi = window
    raw_miss = 0.0 if lo <= lag <= hi else (lo - lag if lag < lo else lag - hi)
    offset = offset_from_window(lag, window, config)

    out["lag_hours"] = round(lag, 2)
    out["offset_hours"] = round(offset, 2)
    out["within_band"] = bool(raw_miss == 0.0)
    out["within_uncertainty"] = bool(raw_miss > 0.0 and offset == 0.0)
    out["score"] = score_from_offset(offset, config)

    if out["within_band"]:
        out["statement"] = (
            f"Its best opportunity was {lag:.1f} h before acquisition, inside the "
            f"{lo:.0f} to {hi:.0f} h origin window."
        )
    elif out["within_uncertainty"]:
        out["statement"] = (
            f"Its best opportunity was {lag:.1f} h before acquisition, {raw_miss:.1f} h outside "
            f"the {lo:.0f} to {hi:.0f} h window but inside the {uncertainty:.0f} h the band "
            "itself is uncertain by, so it is scored as though it were inside."
        )
    else:
        out["statement"] = (
            f"Its best opportunity was {lag:.1f} h before acquisition, {raw_miss:.1f} h outside "
            f"the {lo:.0f} to {hi:.0f} h window and {offset:.1f} h beyond the band's own "
            f"{uncertainty:.0f} h uncertainty. Downweighted, not excluded."
        )
    return out


def describe_factor(age_band: str | None, window_config: dict | None = None, config: dict | None = None) -> str:
    """One line for the UI legend and the dossier."""
    uncertainty, falloff = _config(config)
    if age_band is None:
        return "No age band, so timing is scored neutrally for every vessel."
    lo, hi = window_for_band(age_band, window_config)
    if hi == float("inf"):
        return f"Age band {age_band!r} has no configured window, so timing is scored neutrally."
    return (
        f"Each vessel's best opportunity to be the source is compared against the {lo:.0f} to "
        f"{hi:.0f} h origin window. The window's edges are uncertain by {uncertainty:.0f} h and "
        f"a vessel inside that margin is scored as though it were inside the window, because a "
        f"band derived from contrast and complexity does not resolve a difference that small. "
        f"Past the margin the score falls over about {falloff:.0f} h and then bottoms out. It "
        f"downweights a vessel at an implausible hour, it never rules one out."
    )


def _as_datetime(value) -> datetime.datetime:
    import pandas as pd

    return pd.Timestamp(value).to_pydatetime()
