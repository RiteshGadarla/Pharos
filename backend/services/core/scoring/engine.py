"""Combines named factors into a ranked SuspectScore per vessel. See
PLAN.md section 10.

Weighted sum in log-odds space for F3-F6, which are genuine 0-1
confidence-like scores. F1 (field_integral) and F2 (dark_overlap) are
combined LINEARLY instead, deliberately: they are literal sub-sums of
the origin field's own probability mass, which already sums to 1 over
the whole space-time volume (non-negotiable 1), so they arrive
correctly scaled to [0, 1] on their own. Running logit on values that
can legitimately be nine or ten orders of magnitude apart near zero (a
vessel that never came close to the field vs. one that barely did)
amplifies that ratio into a huge log-odds swing regardless of whether
either value is practically meaningful, which let a vessel with a
literally negligible field_integral edge (~1e-5 vs ~1e-8, both
functionally "never near the field") outweigh another vessel's large,
real dark_overlap signal (~0.16 vs 0.0) during testing. Linear
combination for F1/F2 avoids that failure mode while still respecting
their configured weights. Never trained: weights and thresholds come
from config/scoring.yaml, verbatim, per non-negotiable 3.
"""

from __future__ import annotations

import math

from services.core.schemas import AISTrack, SlickFeatures, SuspectScore
from services.core.scoring.factors import compute_all_factors

LOGIT_EPS = 1e-6

FACTOR_PHRASES = {
    "field_integral": "its track passes through the highest-probability part of the origin field",
    "dark_overlap": "it went dark for a period that overlaps the likely origin area",
    "axis_alignment": "its heading lines up with the slick's own elongation",
    "speed_anomaly": "it slowed well below its own normal transit speed while in the area",
    "course_anomaly": "it changed course sharply around the time of the spill",
    "vessel_plausibility": "its vessel type is one that plausibly carries and could discharge oil",
}


def _logit(p: float) -> float:
    p = min(max(p, LOGIT_EPS), 1.0 - LOGIT_EPS)
    return math.log(p / (1.0 - p))




def build_narrative(factor_contributions: dict[str, float], rank: int) -> str:
    """Templates the top contributing factors into a plain-language
    paragraph. Active voice, no jargon, per PLAN.md section 10."""
    ranked = sorted(factor_contributions.items(), key=lambda kv: kv[1], reverse=True)
    top = [name for name, value in ranked[:3] if value > 0]
    if not top:
        return f"This vessel is ranked {rank}. No single factor stands out; the ranking reflects a broad combination of weak evidence."
    phrases = [FACTOR_PHRASES.get(name, name) for name in top]
    if len(phrases) == 1:
        body = phrases[0]
    elif len(phrases) == 2:
        body = f"{phrases[0]}, and {phrases[1]}"
    else:
        body = f"{phrases[0]}, {phrases[1]}, and {phrases[2]}"
    return f"This vessel is ranked {rank} because {body}."


def score_vessels(
    tracks: list[AISTrack],
    field_ds,
    slick_features: SlickFeatures,
    scoring_config: dict,
) -> list[SuspectScore]:
    """Scores and ranks a list of surviving (non-eliminated) vessels.
    Every SuspectScore.factors dict sums to its total within the
    schema's tolerance, since the contributions ARE what gets summed
    (no separate post-hoc normalisation step for display)."""
    factor_weights = {key: cfg["weight"] for key, cfg in scoring_config["factors"].items()}
    plausibility_table = scoring_config.get("vessel_plausibility_table")

    LINEAR_FACTORS = {"field_integral", "dark_overlap"}

    scores: list[SuspectScore] = []
    for track in tracks:
        raw = compute_all_factors(track, field_ds, slick_features, plausibility_table)
        contributions = {}
        for name, value in raw.items():
            weight = factor_weights[name]
            if name in LINEAR_FACTORS:
                contributions[name] = weight * min(max(value, 0.0), 1.0)
            else:
                contributions[name] = weight * _logit(value)
        total = sum(contributions.values())
        scores.append(
            SuspectScore(
                mmsi=track.mmsi,
                total=total,
                factors=contributions,
                rank=0,  # filled in after sorting
                narrative="",  # filled in after rank is known
            )
        )

    scores.sort(key=lambda s: s.total, reverse=True)
    ranked_scores = []
    for i, score in enumerate(scores, start=1):
        ranked_scores.append(
            score.model_copy(update={"rank": i, "narrative": build_narrative(score.factors, i)})
        )
    return ranked_scores
