"""Fast, no-OpenDrift tests for the validation harness's pure logic (PLAN.md
section 17.1). The harness's end-to-end behaviour (real ensembles, real
scoring) is exercised by scripts/run_validation.py itself, which is slow
enough that it belongs in a pre-demo checklist, not every `make test` run.
"""

from services.core.schemas import SuspectScore
from validation.harness import Accuracy, _culprit_margin, _culprit_rank


def _score(mmsi: str, total: float) -> SuspectScore:
    return SuspectScore(mmsi=mmsi, total=total, factors={"field_integral": total}, rank=0, narrative="")


def test_culprit_rank_finds_the_culprit_by_mmsi():
    scores = [_score("a", 5.0), _score("culprit", 9.0), _score("b", 1.0)]
    scores.sort(key=lambda s: s.total, reverse=True)
    for i, s in enumerate(scores, start=1):
        scores[i - 1] = s.model_copy(update={"rank": i})
    assert _culprit_rank(scores, "culprit") == 1


def test_culprit_rank_is_none_when_culprit_is_not_in_the_list():
    scores = [_score("a", 5.0)]
    assert _culprit_rank(scores, "culprit") is None


def test_culprit_margin_is_positive_when_culprit_leads():
    scores = [_score("culprit", 9.0), _score("a", 5.0), _score("b", 1.0)]
    assert _culprit_margin(scores, "culprit") == 4.0


def test_culprit_margin_is_negative_when_culprit_trails():
    scores = [_score("culprit", 2.0), _score("a", 5.0)]
    assert _culprit_margin(scores, "culprit") == -3.0


def test_culprit_margin_is_zero_when_culprit_is_the_only_candidate():
    scores = [_score("culprit", 2.0)]
    assert _culprit_margin(scores, "culprit") == 0.0


def test_accuracy_counts_eliminated_incidents_separately_from_ranked_ones():
    acc = Accuracy()
    acc.add(rank=1, eliminated=False, margin=3.0)
    acc.add(rank=None, eliminated=True)
    assert acc.n == 2
    assert acc.eliminated == 1
    assert acc.rank1 == 1
    assert acc.elimination_rate == 0.5
    assert acc.mean_margin == 3.0


def test_accuracy_rank3_counts_rank_one_through_three():
    acc = Accuracy()
    for rank in (1, 2, 3, 4):
        acc.add(rank=rank, eliminated=False)
    assert acc.rank1 == 1
    assert acc.rank3 == 3
    assert acc.rank3_accuracy == 0.75


def test_accuracy_with_no_data_reports_zero_not_a_crash():
    acc = Accuracy()
    assert acc.rank1_accuracy == 0.0
    assert acc.rank3_accuracy == 0.0
    assert acc.mean_rank is None
    assert acc.mean_margin is None
    assert acc.elimination_rate == 0.0
