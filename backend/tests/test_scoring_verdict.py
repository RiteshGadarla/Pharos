"""Tests for verdict assignment. See PLAN.md sections 12 and 21:

  "A test that all three verdict classes are reachable from crafted
   fixtures, and that DARK_CONFIRMED requires both conditions."

The second half matters more than the first. DARK_CONFIRMED is the
finding this project exists to be able to make, and a version of it that
fires on either condition alone would turn a quiet scene with no
suspects into a confident announcement that a dark vessel was present.
"""

from __future__ import annotations

import datetime

import numpy as np
import xarray as xr

from services.core.crosscheck.radar import RadarCrossCheck
from services.core.schemas import ShipTarget, SuspectScore
from services.core.scoring.verdict import assign_verdict

VERDICT_CONFIG = {"dominance_margin": 1.5, "dark_floor": 0.0, "eps": 1e-6}


def _score(mmsi: str, total: float, rank: int) -> SuspectScore:
    return SuspectScore(
        mmsi=mmsi, total=total, factors={"field_integral": total}, rank=rank, narrative="test"
    )


def _cross_check(unmatched_masses: dict[str, float]) -> RadarCrossCheck:
    """A cross check carrying only what the verdict logic reads: which
    unmatched targets exist and how much origin field mass sits at each."""
    targets = [
        ShipTarget(
            target_id=tid, scene_id="s", centroid=(68.0, 17.0), pixel_area=64,
            mean_backscatter_db=-4.0,
        )
        for tid in unmatched_masses
    ]
    return RadarCrossCheck(
        targets=targets,
        matched=[],
        unmatched=targets,
        envelope_hits={t.target_id: [] for t in targets},
        field_mass=dict(unmatched_masses),
    )


def test_attributed_when_rank_one_dominates_and_was_broadcasting():
    verdict = assign_verdict(
        case_id="C-1",
        scores=[_score("419000001", 5.0, 1), _score("419000002", 1.0, 2)],
        cross_check=None,
        vessels_with_dark_gaps=set(),
        verdict_config=VERDICT_CONFIG,
    )
    assert verdict.verdict == "ATTRIBUTED"
    assert verdict.top_suspects[0] == "419000001"


def test_ranked_when_the_margin_is_too_small():
    verdict = assign_verdict(
        case_id="C-1",
        scores=[_score("419000001", 5.0, 1), _score("419000002", 4.5, 2)],
        cross_check=None,
        vessels_with_dark_gaps=set(),
        verdict_config=VERDICT_CONFIG,
    )
    assert verdict.verdict == "RANKED"


def test_ranked_when_the_leader_dominates_but_went_dark():
    """A dominant vessel whose track is partly dead-reckoned across a
    gap is not the same claim as a dominant vessel that was observed
    throughout, and the verdict must not flatten the two."""
    verdict = assign_verdict(
        case_id="C-1",
        scores=[_score("419000001", 5.0, 1), _score("419000002", 1.0, 2)],
        cross_check=None,
        vessels_with_dark_gaps={"419000001"},
        verdict_config=VERDICT_CONFIG,
    )
    assert verdict.verdict == "RANKED"
    assert "went dark" in verdict.reasoning


def test_dark_confirmed_needs_both_conditions():
    """Both halves, tested separately, then together."""
    below_floor = [_score("419000001", -3.0, 1)]
    in_field = _cross_check({"t-1": 0.01})
    not_in_field = _cross_check({"t-1": 0.0})

    # Condition 1 alone (no plausible broadcasting vessel, no unmatched
    # target in the field) must not reach DARK_CONFIRMED.
    only_no_suspects = assign_verdict(
        "C-1", below_floor, not_in_field, set(), VERDICT_CONFIG
    )
    assert only_no_suspects.verdict != "DARK_CONFIRMED"

    # Condition 2 alone (an unmatched target in the field, but a
    # perfectly plausible broadcasting suspect) must not reach it either.
    only_unmatched = assign_verdict(
        "C-1", [_score("419000001", 5.0, 1), _score("419000002", 1.0, 2)], in_field, set(), VERDICT_CONFIG
    )
    assert only_unmatched.verdict != "DARK_CONFIRMED"

    # Both together do.
    both = assign_verdict("C-1", below_floor, in_field, set(), VERDICT_CONFIG)
    assert both.verdict == "DARK_CONFIRMED"
    assert both.unmatched_targets == ["t-1"]


def test_dark_confirmed_reasoning_does_not_assert_guilt():
    """The caveats have to travel with the finding, because this is the
    verdict most easily read as an accusation."""
    verdict = assign_verdict(
        "C-1", [_score("419000001", -3.0, 1)], _cross_check({"t-1": 0.01}), set(), VERDICT_CONFIG
    )
    assert verdict.verdict == "DARK_CONFIRMED"
    lowered = verdict.reasoning.lower()
    assert "not an identification" in lowered
    assert "carriage requirements" in lowered


def test_all_three_classes_are_reachable():
    reached = {
        assign_verdict("C", [_score("1", 5.0, 1), _score("2", 1.0, 2)], None, set(), VERDICT_CONFIG).verdict,
        assign_verdict("C", [_score("1", 5.0, 1), _score("2", 4.9, 2)], None, set(), VERDICT_CONFIG).verdict,
        assign_verdict("C", [_score("1", -3.0, 1)], _cross_check({"t-1": 0.01}), set(), VERDICT_CONFIG).verdict,
    }
    assert reached == {"ATTRIBUTED", "RANKED", "DARK_CONFIRMED"}


def test_infrastructure_flag_is_carried_through_every_class():
    for scores, cross in (
        ([_score("1", 5.0, 1), _score("2", 1.0, 2)], None),
        ([_score("1", 5.0, 1), _score("2", 4.9, 2)], None),
        ([_score("1", -3.0, 1)], _cross_check({"t-1": 0.01})),
    ):
        verdict = assign_verdict("C", scores, cross, set(), VERDICT_CONFIG, infrastructure_flag=True)
        assert verdict.infrastructure_flag is True
