"""P8 acceptance test, PLAN.md section 14: "Culprit is rank 1 on the
demo scenario, all three hard negatives are below it, every eliminated
vessel has a reason."
"""

import yaml
import xarray as xr

from services.core.ais.synthetic import generate_demo_scenario
from services.core.scoring.eliminate import eliminate_and_survive
from services.core.scoring.engine import score_vessels
from services.core.schemas import SlickFeatures

FIELD_FIXTURE = "data/fixtures/synthetic_origin_field.nc"
AIS_CONFIG = {"dark_gap_min_minutes": 20, "max_plausible_speed_kn": 30}
CULPRIT_MMSI = "419000001"

SLICK_FEATURES = SlickFeatures(
    detection_id="det-fixture-1", area_km2=1.0, perimeter_km=4.0, complexity_ratio=1.2,
    major_axis_deg=45.0, elongation=3.0, mean_backscatter_db=-25.0, contrast_db=-10.0,
    age_band="fresh", age_reasoning="test",
)


def _scoring_config():
    with open("config/scoring.yaml") as f:
        return yaml.safe_load(f)


def test_culprit_ranks_first_and_every_hard_negative_is_below_it():
    """PLAN.md section 19, the P8 acceptance test.

    Run with the radar cross check in place, because that is how the
    pipeline runs and because the fourth hard negative (419000005)
    exists specifically to be separated by F8: it goes dark over the
    field like the culprit, and the only thing distinguishing them is
    whether radar saw a hull inside the envelope at the acquisition
    instant.
    """
    import pandas as pd

    from services.core.ais.integrity import annotate_integrity
    from services.core.ais.synthetic import inject_ship_targets
    from services.core.crosscheck.radar import run_cross_check

    field_ds = xr.open_dataset(FIELD_FIXTURE)
    scoring_config = _scoring_config()
    tracks = generate_demo_scenario(field_ds, AIS_CONFIG, seed=scoring_config["seed"])
    tracks = annotate_integrity(tracks, scoring_config.get("integrity", {}))

    acquired_at = pd.Timestamp(field_ds["time"].values.max()).to_pydatetime()
    cross_check = run_cross_check(
        inject_ship_targets(tracks, field_ds, acquired_at),
        tracks, field_ds, acquired_at, {"match_radius_m": 1500.0},
    )

    survivors, eliminations = eliminate_and_survive(tracks, field_ds, scoring_config)
    scores = score_vessels(survivors, field_ds, SLICK_FEATURES, scoring_config, cross_check=cross_check)

    # F8 fires for the culprit and for nobody else. Without this the
    # test above would still pass on a scoring engine that simply
    # rewarded darkness, which is the thing F8 is supposed to improve on.
    culprit = next(s for s in scores if s.mmsi == CULPRIT_MMSI)
    assert culprit.factors["radar_confirmed_dark"] > 0
    assert culprit.radar_support is not None
    for s in scores:
        if s.mmsi != CULPRIT_MMSI:
            assert s.factors["radar_confirmed_dark"] == 0, (
                f"F8 fired for {s.mmsi}, which should have no unmatched radar target "
                "in its dark envelope at the acquisition instant"
            )

    eliminated_mmsis = {e.mmsi for e in eliminations}
    assert CULPRIT_MMSI not in eliminated_mmsis, "the culprit itself must never be eliminated"

    culprit_score = next(s for s in scores if s.mmsi == CULPRIT_MMSI)
    assert culprit_score.rank == 1

    other_ranked_mmsis = {s.mmsi for s in scores if s.mmsi != CULPRIT_MMSI}
    for mmsi in other_ranked_mmsis:
        other = next(s for s in scores if s.mmsi == mmsi)
        assert other.total < culprit_score.total


def test_every_eliminated_vessel_has_a_non_empty_reason():
    field_ds = xr.open_dataset(FIELD_FIXTURE)
    scoring_config = _scoring_config()
    tracks = generate_demo_scenario(field_ds, AIS_CONFIG, seed=scoring_config["seed"])
    _, eliminations = eliminate_and_survive(tracks, field_ds, scoring_config)

    assert len(eliminations) > 0  # this scenario is designed to eliminate at least one hard negative
    for e in eliminations:
        assert isinstance(e.reason, str)
        assert len(e.reason) > 0
        assert e.rule


def test_every_demo_vessel_is_accounted_for():
    field_ds = xr.open_dataset(FIELD_FIXTURE)
    scoring_config = _scoring_config()
    tracks = generate_demo_scenario(field_ds, AIS_CONFIG, seed=scoring_config["seed"])
    survivors, eliminations = eliminate_and_survive(tracks, field_ds, scoring_config)

    accounted_for = {t.mmsi for t in survivors} | {e.mmsi for e in eliminations}
    assert accounted_for == {t.mmsi for t in tracks}
    # The culprit plus four hard negatives (PLAN.md section 10). A vessel
    # that is neither scored nor eliminated has vanished without a
    # record, which is the one outcome non-negotiable 2 forbids.
    assert len(accounted_for) == 5


def test_score_vessels_factors_sum_to_total_for_every_survivor():
    field_ds = xr.open_dataset(FIELD_FIXTURE)
    scoring_config = _scoring_config()
    tracks = generate_demo_scenario(field_ds, AIS_CONFIG, seed=scoring_config["seed"])
    survivors, _ = eliminate_and_survive(tracks, field_ds, scoring_config)
    scores = score_vessels(survivors, field_ds, SLICK_FEATURES, scoring_config)
    for s in scores:
        assert abs(sum(s.factors.values()) - s.total) < 1e-6  # the pydantic contract, re-checked end to end
