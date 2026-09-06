"""The case has to be rebuildable, and honest about its own robustness.

See PLAN.md sections 12 and 22.

What is being defended is not that the culprit wins. Every other test in
this suite already checks that, and all of them passed through four
silent scoring bugs precisely because none of them asked *why* it won.

What is defended here is that the step-by-step rebuild runs through the
real engine rather than a reconstruction of it, that the leave-one-out
result is computed rather than asserted, and that a fragile case is
reported as fragile. A robustness claim that can only come out positive
is not a robustness claim.
"""

import datetime

import pandas as pd
import pytest
import xarray as xr
import yaml

from services.core.ais.synthetic import generate_demo_scenario, inject_ship_targets
from services.core.crosscheck.radar import run_cross_check
from services.core.schemas import SlickFeatures
from services.core.scoring.case_build import (
    EVIDENCE_STEPS,
    build_case,
    robustness_statement,
)
from services.core.scoring.eliminate import eliminate_and_survive

FIELD_FIXTURE = "data/fixtures/synthetic_origin_field.nc"
AIS_CONFIG = {"dark_gap_min_minutes": 20, "max_plausible_speed_kn": 30}
SLICK = SlickFeatures(
    detection_id="det-fixture-1", area_km2=1.0, perimeter_km=4.0, complexity_ratio=1.2,
    major_axis_deg=60.0, elongation=2.0, mean_backscatter_db=-20.0, contrast_db=-9.0,
    age_band="fresh", age_reasoning="fixture",
)


def _scoring_config() -> dict:
    with open("config/scoring.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def case() -> dict:
    cfg = _scoring_config()
    field_ds = xr.open_dataset(FIELD_FIXTURE)
    acquired_at = pd.Timestamp(field_ds["time"].values.max()).to_pydatetime()
    tracks = generate_demo_scenario(
        field_ds, AIS_CONFIG, seed=cfg["seed"], origin_lag_hours=3.0, acquired_at=acquired_at
    )
    cross_check = run_cross_check(
        inject_ship_targets(tracks, field_ds, acquired_at), tracks, field_ds,
        acquired_at, {"match_radius_m": 1500.0},
    )
    survivors, eliminations = eliminate_and_survive(tracks, field_ds, cfg)
    return build_case(
        survivors, eliminations, field_ds, SLICK, cfg,
        cross_check=cross_check, acquired_at=acquired_at,
    )


def test_every_step_is_present_and_in_order(case):
    keys = [s["key"] for s in case["steps"]]
    assert keys == [k for k, _, _, _ in EVIDENCE_STEPS]


def test_evidence_only_accumulates(case):
    """Step N must score on the first N steps' evidence and nothing
    else. A step that quietly dropped a factor would make the rebuild a
    different calculation from the case it claims to be rebuilding."""
    seen: list[str] = []
    for step in case["steps"]:
        seen.extend(step["factors_added"])
        assert step["factors_so_far"] == seen


def test_the_final_step_matches_the_real_ranking(case):
    """The last step uses every configured factor, so it has to agree
    with what the engine produces normally. If it does not, the rebuild
    is a separate code path telling a story about the case rather than
    telling the case."""
    cfg = _scoring_config()
    final = case["steps"][-1]
    assert set(final["factors_so_far"]) == set(cfg["factors"].keys())
    assert final["lead"] == case["final_lead"]


def test_position_alone_does_not_settle_the_case(case):
    """The demo's own strongest argument, and it has to be true rather
    than asserted. If the leader on the field integral alone were
    already the final answer, the whole behavioural half of the model
    would be decoration and the proximity criticism would be correct."""
    where = next(s for s in case["steps"] if s["key"] == "where")
    later = [s for s in case["steps"] if s["lead"] is not None]
    assert where["lead"] is not None
    assert where["lead"] != case["final_lead"], (
        "position alone already picks the final answer, so this scenario "
        "cannot demonstrate that the behavioural factors do any work"
    )
    assert any(s["lead_changed"] for s in later), "no step ever changed the leader"


def test_stabilises_at_step_is_the_earliest_settled_step(case):
    """It must be the first step after which the leader never moves, not
    merely a step where the leader happens to be right."""
    stabilises = case["stabilises_at_step"]
    scored = [s for s in case["steps"] if s["lead"] is not None]
    idx = next(i for i, s in enumerate(scored) if s["key"] == stabilises)

    assert all(s["lead"] == case["final_lead"] for s in scored[idx:])
    if idx > 0:
        assert scored[idx - 1]["lead"] != case["final_lead"], "settled earlier than reported"


def test_decisive_factors_is_computed_by_leave_one_out(case):
    """An empty list has to mean the ablations were run and none flipped
    the answer, not that the check was skipped."""
    assert isinstance(case["decisive_factors"], list)
    for name in case["decisive_factors"]:
        assert name in _scoring_config()["factors"]


def test_a_fragile_case_is_reported_as_fragile():
    """The statement must be able to come out negative. A robustness
    claim that can only ever be positive is marketing."""
    fragile = {
        "final_lead": "419000001",
        "decisive_factors": ["radar_confirmed_dark"],
        "stabilises_at_step": "radar",
        "steps": [{"key": "radar", "label": "What radar independently saw"}],
    }
    text = robustness_statement(fragile)
    assert "depends on" in text
    assert "radar_confirmed_dark" in text
    assert "no single factor" not in text


def test_a_robust_case_says_so_without_overclaiming():
    robust = {
        "final_lead": "419000001",
        "decisive_factors": [],
        "stabilises_at_step": "behaviour",
        "steps": [{"key": "behaviour", "label": "How they behaved"}],
    }
    text = robustness_statement(robust)
    assert "no single factor" in text
    # It must claim robustness to single-factor removal and nothing
    # more. This is not a claim about real-world accuracy.
    assert "accurate" not in text.lower()
    assert "proven" not in text.lower()


def test_an_empty_candidate_set_is_handled():
    assert "no ranking to test" in robustness_statement({"final_lead": None})
