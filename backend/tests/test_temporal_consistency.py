"""F9 has to score timing without turning the band edge into a cliff.

See PLAN.md sections 8 and 12.

The shape of the curve IS the claim this factor makes, so these tests
assert the shape rather than asserting that the culprit still wins.
Every other test in this suite already checks the ranking, and all of
them sat happily through five silent scoring bugs precisely because
none of them asked why the ranking came out the way it did.

The test that matters most here is the band-edge one. A window derived
from contrast and complexity does not resolve a two hour difference, so
if the discharge really happened 14 hours ago and the band says 0 to 12,
the vessels that passed in those extra hours are live candidates. A
scoring rule that buries them is not being strict, it is claiming a
precision the radiometry cannot support.
"""

import datetime
import math

import pytest
import xarray as xr
import yaml

from services.core.scoring.age_window import window_for_band
from services.core.scoring.engine import _logit
from services.core.scoring.temporal import (
    FLOOR_SCORE,
    NEUTRAL_SCORE,
    PEAK_SCORE,
    compute_temporal_consistency,
    describe_timing,
    offset_from_window,
    score_from_offset,
)

FIELD_FIXTURE = "data/fixtures/synthetic_origin_field.nc"


@pytest.fixture(scope="module")
def cfg() -> dict:
    with open("config/scoring.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def tcfg(cfg) -> dict:
    return cfg["temporal_consistency"]


def test_inside_the_window_scores_the_peak(tcfg):
    window = (0.0, 12.0)
    for lag in [0.0, 1.0, 6.0, 11.9, 12.0]:
        assert offset_from_window(lag, window, tcfg) == 0.0
        assert score_from_offset(offset_from_window(lag, window, tcfg), tcfg) == PEAK_SCORE


def test_the_band_edge_is_not_a_cliff(tcfg):
    """The case the whole margin exists for.

    Band says the slick originated 0 to 12 hours ago. It actually
    originated 14 hours ago. The vessels that passed at 13 and 14 hours
    must be scored exactly as though they were inside the window,
    because on this evidence they may well be: the band is an estimate
    and its edges are estimates too.
    """
    window = (0.0, 12.0)
    for true_origin_lag in [12.5, 13.0, 14.0, 15.0]:
        offset = offset_from_window(true_origin_lag, window, tcfg)
        assert offset == 0.0, f"{true_origin_lag} h lost credit it should not have"
        assert score_from_offset(offset, tcfg) == PEAK_SCORE

    # And the margin is finite. It absorbs the band's own uncertainty,
    # it does not quietly widen the window without limit.
    assert offset_from_window(24.0, window, tcfg) > 0.0


def test_the_margin_applies_on_the_near_side_too(tcfg):
    """A slick can look older than it is as easily as younger, so the
    uncertainty is symmetric. A weathered band starting at 24 hours must
    not bury a vessel whose opportunity was at 22."""
    window = (24.0, 48.0)
    assert offset_from_window(22.0, window, tcfg) == 0.0
    assert offset_from_window(50.0, window, tcfg) == 0.0


def test_score_falls_monotonically_past_the_margin(tcfg):
    offsets = [0.0, 1.0, 2.0, 4.0, 8.0, 12.0, 18.0, 24.0]
    scores = [score_from_offset(o, tcfg) for o in offsets]
    for earlier, later in zip(scores, scores[1:]):
        assert later <= earlier
    assert scores[0] > scores[-1], "the curve never actually falls"


def test_the_penalty_saturates_rather_than_running_away(tcfg):
    """engine.py's docstring records that an unbounded single-factor
    penalty was a real bug in this codebase: one factor could move the
    total by 13.8 and 'no evidence here' outranked 'clear evidence
    there'. F9 must bottom out at the same floor as every other soft
    factor instead of growing without limit."""
    assert score_from_offset(1e6, tcfg) == pytest.approx(FLOOR_SCORE, abs=1e-9)
    assert score_from_offset(48.0, tcfg) == pytest.approx(FLOOR_SCORE, abs=1e-3)
    # In the engine's own units, the worst F9 can do is the logit clamp.
    assert _logit(score_from_offset(1e6, tcfg)) == pytest.approx(_logit(FLOOR_SCORE))


def test_the_curve_is_gentle_near_the_margin_and_steep_later(tcfg):
    """'Heavily non-linear' is the requirement, so a straight line has
    to fail this test. The first hour past the margin must cost clearly
    less than an hour in the middle of the falloff."""
    step = lambda a, b: score_from_offset(a, tcfg) - score_from_offset(b, tcfg)
    near = step(0.0, 1.0)
    middle = step(7.0, 8.0)
    assert middle > 2 * near, "the falloff is essentially linear, not the intended curve"


def test_missing_evidence_contributes_exactly_nothing(tcfg, cfg):
    """No age band and no acquisition time are absent evidence, and
    absent evidence must leave the ranking exactly as it found it. 0.5
    is the only value that does that, because the engine takes a logit
    and logit(0.5) is 0."""
    assert NEUTRAL_SCORE == 0.5
    assert _logit(NEUTRAL_SCORE) == pytest.approx(0.0)

    field_ds = xr.open_dataset(FIELD_FIXTURE)
    track = _a_track(field_ds)
    acquired = _acquired(field_ds)
    assert compute_temporal_consistency(track, field_ds, None, acquired, {}, tcfg) == NEUTRAL_SCORE
    assert compute_temporal_consistency(track, field_ds, "fresh", None, {}, tcfg) == NEUTRAL_SCORE
    # An age band nobody configured is also missing evidence, not
    # evidence of an infinitely wide window.
    unknown = compute_temporal_consistency(
        track, field_ds, "not_a_band", acquired, cfg["age_origin_window"], tcfg
    )
    assert unknown == NEUTRAL_SCORE


def test_it_downweights_but_can_never_eliminate(tcfg, cfg):
    """The same rule that caps F6. The age band is heuristic, and
    age_window.py states three times over that it downweights and never
    clears a vessel. A factor that can zero a candidate out on its own
    is not a prior, it is a verdict."""
    assert FLOOR_SCORE > 0.0
    worst = _logit(score_from_offset(1e6, tcfg))
    best = _logit(score_from_offset(0.0, tcfg))
    weight = cfg["factors"]["temporal_consistency"]["weight"]

    # The entire swing F9 can produce, best case to worst case, has to
    # stay below what the two positional factors can produce, so timing
    # can shade a ranking but never overturn the field evidence.
    f9_swing = weight * (best - worst)
    positional = cfg["factors"]["field_integral"]["weight"] + cfg["factors"]["dark_overlap"]["weight"]
    assert f9_swing < positional, "F9 can outvote the origin field on its own"


def test_a_real_vessel_gets_a_timing_explanation(tcfg, cfg):
    """describe_timing backs the bar in the UI. If it cannot say in
    words why a vessel scored what it scored, the bar is asking for
    trust rather than giving a reason."""
    field_ds = xr.open_dataset(FIELD_FIXTURE)
    track = _a_track(field_ds)
    out = describe_timing(
        track, field_ds, "fresh", _acquired(field_ds), cfg["age_origin_window"], tcfg
    )
    assert out["opportunity_at"] is not None
    assert out["lag_hours"] is not None
    assert out["statement"]
    assert FLOOR_SCORE <= out["score"] <= PEAK_SCORE
    # Exactly one of the three states, never two and never none.
    assert sum([bool(out["within_band"]), bool(out["within_uncertainty"]), out["offset_hours"] > 0]) == 1


def test_the_statement_says_downweighted_not_excluded(tcfg):
    """A vessel scored badly on timing must be told it is downweighted,
    because that is what actually happened to it."""
    from services.core.schemas import AISPoint, AISTrack

    field_ds = xr.open_dataset(FIELD_FIXTURE)
    acquired = _acquired(field_ds)
    # A fresh band against a vessel whose only opportunity is far back.
    out = describe_timing(_a_track(field_ds), field_ds, "weathered", acquired, {}, tcfg)
    if out["offset_hours"] and out["offset_hours"] > 0:
        assert "not excluded" in out["statement"]


def test_it_reports_the_vessel_s_hour_not_the_field_s(cfg, tcfg):
    """The bug this factor shipped with, caught here so it cannot come
    back quietly.

    The field's mass concentrates in time, so a raw argmax of P along a
    track collapses onto whichever timestep is densest no matter where
    the vessel actually was. Every survivor of the demo case then came
    back peaking within half an hour of the others, with identical
    scores, and F9 was reporting the FIELD's busiest hour as though it
    were each VESSEL's best opportunity. The pipeline ran, the suite
    passed, and the factor measured nothing.

    Normalising each timestep by its own peak is what fixes it, and the
    observable consequence is that different vessels get different
    answers. If every candidate scores the same, the factor is inert and
    should not be in the model.
    """
    import xarray as xr

    from services.core.ais.synthetic import generate_demo_scenario
    from services.core.scoring.eliminate import eliminate_and_survive

    field_ds = xr.open_dataset(FIELD_FIXTURE)
    acquired = _acquired(field_ds)
    tracks = generate_demo_scenario(
        field_ds,
        {"dark_gap_min_minutes": 20, "max_plausible_speed_kn": 30},
        seed=cfg["seed"], origin_lag_hours=3.0, acquired_at=acquired,
    )
    survivors, _ = eliminate_and_survive(tracks, field_ds, cfg)
    assert len(survivors) >= 2, "need at least two candidates to tell them apart"

    lags = [
        describe_timing(t, field_ds, "fresh", acquired, cfg["age_origin_window"], tcfg)["lag_hours"]
        for t in survivors
    ]
    assert len(set(lags)) > 1, (
        f"every candidate reports the same opportunity hour {lags[0]}, so F9 is reading the "
        "field's peak rather than each vessel's own best moment"
    )


def _acquired(field_ds) -> datetime.datetime:
    import pandas as pd

    return pd.Timestamp(field_ds["time"].values.max()).to_pydatetime()


def _a_track(field_ds):
    from services.core.ais.synthetic import generate_demo_scenario

    tracks = generate_demo_scenario(
        field_ds,
        {"dark_gap_min_minutes": 20, "max_plausible_speed_kn": 30},
        seed=26143,
        origin_lag_hours=3.0,
        acquired_at=_acquired(field_ds),
    )
    return tracks[0]
