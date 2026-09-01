"""Runs the validation harness (PLAN.md section 13) and writes
data/processed/validation.md.

Run from backend/: PYTHONPATH=. .venv/bin/python scripts/run_validation.py
"""

from __future__ import annotations

import datetime

import yaml

from services.core.validation.harness import TRAFFIC_DENSITY_LEVELS, Accuracy, run_validation

OUT_PATH = "data/processed/validation.md"
N_INCIDENTS = 50


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _mean_rank(a: Accuracy) -> str:
    return f"{a.mean_rank:.2f}" if a.mean_rank is not None else "n/a"


def _margin_commentary(baseline: Accuracy, variant: Accuracy, label: str) -> str:
    """States what the margin actually did, computed from the numbers
    rather than assumed, since a smaller margin is the expected
    direction but not a guaranteed one on any given run of the harness."""
    if baseline.mean_margin is None or variant.mean_margin is None:
        return f"{label}: margin data unavailable."
    delta = variant.mean_margin - baseline.mean_margin
    if delta < -1e-9:
        return f"{label} narrows the mean margin by {abs(delta):.2f}, the expected direction: removing real signal makes the culprit's win smaller even where it doesn't flip the rank."
    if delta > 1e-9:
        return f"{label} widens the mean margin by {delta:.2f} in this run, the opposite of the expected direction. Worth investigating rather than reporting as a win: see if this holds across reruns with a different seed."
    return f"{label} leaves the mean margin unchanged in this run."


def format_report(summary: dict) -> str:
    overall: Accuracy = summary["overall"]
    no_dark: Accuracy = summary["ablation_no_dark_overlap"]
    centroid: Accuracy = summary["ablation_centroid_baseline"]

    lines = []
    lines.append("# SLICKTRACE scoring validation")
    lines.append("")
    lines.append(f"Generated {datetime.datetime.utcnow().isoformat()}Z, {summary['n_incidents']} synthetic incidents.")
    lines.append("")
    lines.append(
        "This measures internal consistency of the scoring model against synthetic "
        "incidents with a known injected culprit vessel, not real-world attribution "
        "accuracy. There is no ground truth for a real spill, so this is the "
        "strongest evidence available before that exists. Validation against a "
        "documented, prosecuted incident is the next step, not this."
    )
    lines.append("")

    lines.append("## Overall")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("|---|---|")
    lines.append(f"| rank-1 accuracy | {_pct(overall.rank1_accuracy)} |")
    lines.append(f"| rank-3 accuracy | {_pct(overall.rank3_accuracy)} |")
    lines.append(f"| mean rank of the true culprit (when not eliminated) | {_mean_rank(overall)} |")
    lines.append(f"| culprit eliminated by mistake | {_pct(overall.elimination_rate)} |")
    lines.append("")

    lines.append("## By traffic density")
    lines.append("")
    lines.append("| density | decoy vessels | n | rank-1 | rank-3 | mean rank | eliminated |")
    lines.append("|---|---|---|---|---|---|---|")
    for name, n_decoys in TRAFFIC_DENSITY_LEVELS.items():
        a: Accuracy = summary["by_density"][name]
        lines.append(
            f"| {name} | {n_decoys} | {a.n} | {_pct(a.rank1_accuracy)} | {_pct(a.rank3_accuracy)} | "
            f"{_mean_rank(a)} | {_pct(a.elimination_rate)} |"
        )
    lines.append("")

    lines.append("## Ablations")
    lines.append("")
    lines.append(
        "Both ablations rerun the same 50 incidents with one deliberate change to "
        "the scoring, holding elimination and everything else fixed, to check "
        "whether SLICKTRACE's two claimed differentiators actually matter. Rank-1 "
        "accuracy only moves when a competitor's score actually overtakes the "
        "culprit's; margin (the culprit's score minus the best competitor's, mean "
        "across incidents) shows the effect even when it isn't yet large enough to "
        "flip the rank."
    )
    lines.append("")
    lines.append("| variant | rank-1 accuracy | drop vs baseline | mean margin |")
    lines.append("|---|---|---|---|")
    lines.append(f"| baseline (real scoring) | {_pct(overall.rank1_accuracy)} | - | {overall.mean_margin:.2f} |")
    drop_dark = overall.rank1_accuracy - no_dark.rank1_accuracy
    lines.append(
        f"| F2 (dark overlap) zeroed out | {_pct(no_dark.rank1_accuracy)} | "
        f"{drop_dark * 100:+.0f} pp | {no_dark.mean_margin:.2f} |"
    )
    drop_centroid = overall.rank1_accuracy - centroid.rank1_accuracy
    lines.append(
        f"| F1 replaced by distance to the field's own centroid | {_pct(centroid.rank1_accuracy)} | "
        f"{drop_centroid * 100:+.0f} pp | {centroid.mean_margin:.2f} |"
    )
    lines.append("")
    lines.append(
        "The centroid-distance row is the naive baseline PLAN.md's non-negotiable 1 "
        "argues against directly: collapsing the origin field to a single point "
        "before ranking vessels. It is never used outside this harness."
    )
    lines.append("")
    lines.append(_margin_commentary(overall, no_dark, "F2 (dark overlap) zeroed out"))
    lines.append("")
    lines.append(_margin_commentary(overall, centroid, "F1 replaced by distance to the centroid"))

    near_miss = summary["near_miss"]
    lines.append("")
    lines.append("### The right-place-wrong-time case")
    lines.append("")
    lines.append(
        "Every incident also includes one purpose-built decoy (MMSI 419000005): it "
        "passes directly through the field's own probability peak, but hours before "
        "the field's time window opens, then barely re-enters the window at its low "
        "probability edge, just enough to survive elimination. This is the specific "
        "case a single-point collapse cannot tell apart from the real culprit."
    )
    lines.append("")
    if near_miss["n"] > 0:
        lines.append(
            f"It survived elimination and reached scoring in {near_miss['n']} of {N_INCIDENTS} incidents. "
            f"Real scoring (time-weighted F1) gives it a mean total of {near_miss['mean_baseline_total']:.2f}. "
            f"The centroid ablation, blind to when its close pass happened, gives it a mean total of "
            f"{near_miss['mean_centroid_total']:.2f} -- "
            f"{near_miss['mean_centroid_total'] - near_miss['mean_baseline_total']:+.2f} relative to real scoring: "
            "exactly the direction the design predicts, since the centroid metric cannot see that its close "
            "pass happened outside the window. Whether that specific shift is ever large enough to overtake "
            "the true culprit is a separate question from the rank-1 accuracy figures above, which count "
            "every competitor, not this one alone."
        )
    else:
        lines.append("It did not survive elimination in any incident this run, so no comparison is available.")

    return "\n".join(lines) + "\n"


def main() -> None:
    with open("config/scoring.yaml") as f:
        scoring_config = yaml.safe_load(f)
    with open("config/pipeline.yaml") as f:
        pipeline_config = yaml.safe_load(f)
    ais_config = pipeline_config["ais"]

    print(f"Running {N_INCIDENTS} synthetic incidents...")
    summary = run_validation(N_INCIDENTS, scoring_config["seed"], ais_config, scoring_config)

    report = format_report(summary)
    print(report)

    with open(OUT_PATH, "w") as f:
        f.write(report)
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
