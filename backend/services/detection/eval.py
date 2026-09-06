"""Per class IoU and F1 on a held out split. See PLAN.md section 5,
"Evaluation, do not skip".

NOT YET RUN. It is blocked on the two corpora PLAN.md section 4A names,
neither of which is on disk:

  Zenodo Sentinel-1 SAR oil spill dataset, Parts I to III
      DOIs 10.5281/zenodo.8346860, 8253899, 13761290. No auth.
      The primary corpus, and named in the problem statement. Sigma0 in
      decibels, which is the same radiometric space render.py's step 2
      produces, so running the model on it through render steps 3 to 5
      tests the render chain and the model together rather than
      separately. Binary masks: oil versus background only.

  Five class SAR oil spill dataset (Krestenitis style)
      By request. The secondary corpus. Sea surface, oil spill, look
      alike, ship, land. The only source of a look alike number and of a
      ship class number, and the Zenodo set can provide neither.

The functions below are written against those two shapes so that
producing the number is a matter of pointing them at the data, not of
writing the evaluation.

WHY THIS MODULE MATTERS MORE THAN ITS SIZE SUGGESTS. The model card
reports 0.9668 F1, self reported, with no split stated and no per class
breakdown. On this taxonomy the background class dominates pixel counts,
so a near 0.97 aggregate says almost nothing about oil class
performance, where published work on comparable data sits far lower.
Non-negotiable 8: never surface that figure in the UI, the README, the
dossier, or any slide. This module's job is to produce the honest number
to replace it with, with the class name attached, even if oil class IoU
turns out to be 0.6.

Until it runs, the dossier states plainly that the number is not
available rather than substituting one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ClassMetrics:
    class_name: str
    iou: float
    f1: float
    support_px: int


def confusion_counts(pred: np.ndarray, truth: np.ndarray, class_index: int) -> tuple[int, int, int]:
    """(true positives, false positives, false negatives) for one class."""
    p = pred == class_index
    t = truth == class_index
    return int((p & t).sum()), int((p & ~t).sum()), int((~p & t).sum())


def metrics_for_class(pred: np.ndarray, truth: np.ndarray, class_index: int, class_name: str) -> ClassMetrics:
    tp, fp, fn = confusion_counts(pred, truth, class_index)
    iou = tp / (tp + fp + fn) if (tp + fp + fn) else float("nan")
    f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else float("nan")
    return ClassMetrics(class_name=class_name, iou=iou, f1=f1, support_px=tp + fn)


def evaluate(preds: list[np.ndarray], truths: list[np.ndarray], class_names: list[str]) -> list[ClassMetrics]:
    """Per class IoU and F1 over a whole split.

    Accumulated over the split rather than averaged per image, so a
    handful of images that happen to contain no oil cannot drag the oil
    class figure toward an undefined value or an accidental 1.0.
    """
    stacked_pred = np.concatenate([p.ravel() for p in preds])
    stacked_truth = np.concatenate([t.ravel() for t in truths])
    return [
        metrics_for_class(stacked_pred, stacked_truth, i, name)
        for i, name in enumerate(class_names)
    ]


def format_table(metrics: list[ClassMetrics], corpus_name: str) -> str:
    """The table that goes on the slide, with the class name attached to
    every number and no aggregate row.

    There is deliberately no "overall" line. An aggregate on a taxonomy
    this unbalanced is the exact figure non-negotiable 8 forbids, and
    printing one here would put it back into circulation through the
    front door.
    """
    lines = [
        f"Per class IoU and F1, {corpus_name}",
        "",
        f"{'class':<14}{'IoU':>8}{'F1':>8}{'support (px)':>16}",
        "-" * 46,
    ]
    for m in metrics:
        lines.append(f"{m.class_name:<14}{m.iou:>8.3f}{m.f1:>8.3f}{m.support_px:>16,}")
    lines += [
        "",
        "No aggregate figure is reported. Background pixels dominate this taxonomy,",
        "so an aggregate says nothing about oil class performance. Read the oil row.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(
        "eval.py: the metrics are implemented, but neither evaluation corpus is on "
        "disk yet. See the module docstring and PLAN.md section 4A: start the Zenodo "
        "Part I download (roughly 40.7 GB, the longest lead item in the project) and "
        "request the five class dataset."
    )
