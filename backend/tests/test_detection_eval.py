"""Tests for the per class evaluation metrics. See PLAN.md section 5.

The corpora are not on disk yet, so these test the metric arithmetic on
hand-built masks rather than a real split. That is worth having on its
own: when the Zenodo download lands, the number it produces should be
wrong only if the model is wrong, not because the IoU formula was never
checked.

The last test is the one that matters most. Non-negotiable 8 forbids
surfacing an aggregate figure without a class name attached, and the
easiest way to break that rule by accident is for the table formatter to
grow an "overall" row.
"""

from __future__ import annotations

import numpy as np
import pytest

from services.detection.eval import confusion_counts, evaluate, format_table, metrics_for_class

CLASSES = ["background", "oil", "look_alike", "ship", "wake"]


def test_a_perfect_prediction_scores_one():
    truth = np.array([[0, 1], [1, 0]])
    m = metrics_for_class(truth.copy(), truth, class_index=1, class_name="oil")
    assert m.iou == pytest.approx(1.0)
    assert m.f1 == pytest.approx(1.0)
    assert m.support_px == 2


def test_a_class_the_model_never_predicts_scores_zero_not_nan():
    """The failure that matters: a detector that finds no oil at all must
    score 0 on oil, not silently produce an undefined value that an
    averaging step then drops."""
    truth = np.array([[0, 1], [1, 0]])
    pred = np.zeros_like(truth)
    m = metrics_for_class(pred, truth, class_index=1, class_name="oil")
    assert m.iou == pytest.approx(0.0)
    assert m.f1 == pytest.approx(0.0)
    assert m.support_px == 2


def test_a_class_absent_from_both_is_undefined_rather_than_perfect():
    """An absent class is not a class the model got right. nan is the
    honest value, and it keeps a class nobody has any data for from
    inflating a table."""
    truth = np.zeros((2, 2), dtype=int)
    m = metrics_for_class(truth.copy(), truth, class_index=3, class_name="ship")
    assert np.isnan(m.iou)
    assert np.isnan(m.f1)


def test_confusion_counts_are_what_they_claim():
    truth = np.array([1, 1, 0, 0])
    pred = np.array([1, 0, 1, 0])
    tp, fp, fn = confusion_counts(pred, truth, class_index=1)
    assert (tp, fp, fn) == (1, 1, 1)


def test_evaluation_accumulates_over_the_split_rather_than_averaging_per_image():
    """A handful of images containing no oil must not drag the oil figure
    toward an undefined value or an accidental 1.0. Accumulating over the
    whole split is what prevents that."""
    with_oil_truth = np.array([[0, 1], [1, 0]])
    with_oil_pred = np.array([[0, 1], [0, 0]])  # finds half the oil
    no_oil = np.zeros((2, 2), dtype=int)

    metrics = evaluate([with_oil_pred, no_oil], [with_oil_truth, no_oil], CLASSES)
    oil = next(m for m in metrics if m.class_name == "oil")
    # 1 true positive, 0 false positives, 1 false negative across the split
    assert oil.iou == pytest.approx(0.5)
    assert oil.support_px == 2


def test_the_table_never_prints_an_aggregate():
    """Non-negotiable 8. An aggregate on a taxonomy this unbalanced is
    exactly the 0.9668-shaped figure the plan forbids, and a formatter
    that grows an 'overall' row would put it back into circulation
    through the front door."""
    truth = np.array([[0, 1], [1, 0]])
    metrics = evaluate([truth.copy()], [truth], CLASSES)
    table = format_table(metrics, "test corpus")
    lowered = table.lower()
    assert "overall" not in lowered
    assert "mean" not in lowered
    assert "0.9668" not in table
    # every number is on a line that starts with a class name
    for name in CLASSES:
        assert name in table
