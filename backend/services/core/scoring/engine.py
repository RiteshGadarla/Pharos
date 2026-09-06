"""Combines named factors into a ranked SuspectScore per vessel. See
PLAN.md section 12.

Weighted sum in log-odds space for F3-F7, which are genuine 0-1
confidence-like scores. F1 (field_integral), F2 (dark_overlap) and F8
(radar_confirmed_dark) are combined LINEARLY instead, deliberately.
Running logit on values that can legitimately be nine or ten orders of
magnitude apart near zero (a vessel that never came close to the field
versus one that barely did) amplifies that ratio into a huge log-odds
swing regardless of whether either value is practically meaningful,
which let a vessel with a literally negligible field_integral edge
(~1e-5 vs ~1e-8, both functionally "never near the field") outweigh
another vessel's large, real dark_overlap signal during testing.

F1 and F2 are also NORMALISED ACROSS THE CANDIDATE SET before they are
weighted, which PLAN.md section 12 specifies for F1 in as many words
("Normalise across all candidate vessels to 0-1") and which F2 needs for
the same reason. Both are literal sub-sums of the origin field's own
probability mass. That mass sums to 1 over the whole space-time volume,
so on a 98 by 38 by 35 grid a track through the densest part of the
field still integrates to something around 1e-4. Clamping that raw value
to [0, 1] and weighting it, which is what this module used to do, left
the primary factor contributing about 0.001 to a total in the range of
several units: F1 was switched off in all but name, and the ranking was
being decided by the behavioural factors alone.

Normalising against the strongest candidate asks the question that
actually matters, which is "which of these vessels best explains the
distribution", and it is safe here precisely because it runs after
elimination: scoring/eliminate.py has already removed every vessel with
no temporal overlap and no spatial support, so the survivors all have
real mass and the comparison is between genuine candidates rather than
between a best-of-nothing. Never trained: weights and thresholds come
from config/scoring.yaml, verbatim, per non-negotiable 3.
"""

from __future__ import annotations

import math

from services.core.forecast.forward import assert_not_scoring_input
from services.core.schemas import AISTrack, SlickFeatures, SuspectScore
from services.core.scoring.age_window import field_time_weights
from services.core.scoring.factors import _all_field_times, compute_all_factors

# Clamp on the logit's input, which bounds how much any one factor can
# move the total: logit(0.05) is about -2.94, so a single factor tops out
# near a 19:1 likelihood ratio either way.
#
# This was 1e-6, which allowed +/- 13.8, a million to one. No soft
# behavioural factor supports a claim that strong, and in practice the
# bound was reached constantly, because F3 to F5 legitimately return 0.0
# when they find nothing. A vessel that simply never slowed down scored
# logit(0) on F4 and picked up -13.8, which buried every real positive
# signal the other factors found and let "no evidence here" outrank
# "clear evidence there". Absence of evidence has to stay near neutral,
# and no one factor should be able to decide the ranking by itself.
LOGIT_EPS = 0.05

FACTOR_PHRASES = {
    "field_integral": "its track passes through the highest-probability part of the origin field",
    "dark_overlap": "it went dark for a period that overlaps the likely origin area",
    "axis_alignment": "its heading lines up with the slick's own elongation",
    "speed_anomaly": "it slowed well below its own normal transit speed while in the area",
    "course_anomaly": "it changed course sharply around the time of the spill",
    "vessel_plausibility": "its vessel type is one that plausibly carries and could discharge oil",
    "ais_integrity": "its AIS reporting is internally inconsistent in a way that a working transponder does not explain",
    "radar_confirmed_dark": "the radar image itself shows a hull inside its dark-period envelope that AIS never reported",
    "temporal_consistency": "the hour it was over the origin area matches when a slick in this condition would have been discharged",
}


def _logit(p: float) -> float:
    p = min(max(p, LOGIT_EPS), 1.0 - LOGIT_EPS)
    return math.log(p / (1.0 - p))




# Smallest contribution the narrative will describe in words. Below
# this a factor is not evidence, it is rounding, and the phrases in
# FACTOR_PHRASES are far too confident for it: a field_integral
# contribution of 0.0004 would otherwise be read out as "its track
# passes through the highest-probability part of the origin field".
NARRATIVE_MIN_CONTRIBUTION = 0.05


def build_narrative(factor_contributions: dict[str, float], rank: int) -> str:
    """Templates the top contributing factors into a plain-language
    paragraph. Active voice, no jargon, per PLAN.md section 10."""
    ranked = sorted(factor_contributions.items(), key=lambda kv: kv[1], reverse=True)
    top = [name for name, value in ranked[:3] if value >= NARRATIVE_MIN_CONTRIBUTION]
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
    cross_check=None,
    acquired_at=None,
) -> list[SuspectScore]:
    """Scores and ranks a list of surviving (non-eliminated) vessels.
    Every SuspectScore.factors dict sums to its total within the
    schema's tolerance, since the contributions ARE what gets summed
    (no separate post-hoc normalisation step for display).

    cross_check is the scene's RadarCrossCheck (crosscheck/radar.py),
    which F8 reads. None means the scene had no ship target extraction:
    F8 then contributes nothing to any vessel, which is correct, since
    an unrun check is not evidence either way.

    field_ds must be the backward origin field. A forward forecast has
    the same dims and dtype and would score silently and wrongly, so it
    is rejected here rather than trusted to the caller."""
    assert_not_scoring_input(field_ds)

    factor_weights = {key: cfg["weight"] for key, cfg in scoring_config["factors"].items()}
    plausibility_table = scoring_config.get("vessel_plausibility_table")

    # Combined linearly rather than through a logit, see the module
    # docstring.
    LINEAR_FACTORS = {"field_integral", "dark_overlap", "radar_confirmed_dark"}
    # Of those, the two that are raw probability mass and therefore need
    # normalising against the strongest candidate. F8 is already scaled
    # against the field's own peak inside scoring/factors.py, so it
    # arrives on a 0 to 1 scale of its own and must not be renormalised:
    # doing so would inflate a weak radar hit to a strong one whenever
    # it happened to be the only radar hit in the case.
    CROSS_NORMALISED = {"field_integral", "dark_overlap"}

    # The origin window the slick's own condition implies. The backward
    # field cannot tell a 48 hour old origin from a 1 hour old one; the
    # slick's contrast and complexity can, weakly, and this is where
    # that evidence enters the ranking. See scoring/age_window.py.
    time_weights = None
    if acquired_at is not None and slick_features is not None:
        time_weights = field_time_weights(
            list(_all_field_times(field_ds)),
            acquired_at,
            slick_features.age_band,
            scoring_config.get("age_origin_window", {}),
        )

    raw_by_mmsi: dict[str, dict[str, float]] = {}
    radar_target_by_mmsi: dict[str, str | None] = {}
    for track in tracks:
        raw, radar_target_id = compute_all_factors(
            track, field_ds, slick_features, plausibility_table,
            cross_check=cross_check, time_weights=time_weights,
            acquired_at=acquired_at,
            age_window_config=scoring_config.get("age_origin_window", {}),
            temporal_config=scoring_config.get("temporal_consistency", {}),
        )
        raw_by_mmsi[track.mmsi] = raw
        radar_target_by_mmsi[track.mmsi] = radar_target_id

    normalisers = {
        name: max((raw[name] for raw in raw_by_mmsi.values()), default=0.0)
        for name in CROSS_NORMALISED
    }

    scores: list[SuspectScore] = []
    for track in tracks:
        raw = raw_by_mmsi[track.mmsi]
        contributions = {}
        for name, value in raw.items():
            # A factor the config does not weight is a factor this
            # deployment has switched off, which is how the validation
            # harness runs its ablations. Skip it rather than crashing.
            if name not in factor_weights:
                continue
            weight = factor_weights[name]
            if name in CROSS_NORMALISED:
                # A zero normaliser means no candidate had any of this
                # evidence at all. Every vessel then scores 0 on it,
                # which is correct: nobody is distinguished by evidence
                # nobody has.
                denominator = normalisers[name]
                scaled = (value / denominator) if denominator > 0 else 0.0
                contributions[name] = weight * min(max(scaled, 0.0), 1.0)
            elif name in LINEAR_FACTORS:
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
                radar_support=radar_target_by_mmsi[track.mmsi],
            )
        )

    scores.sort(key=lambda s: s.total, reverse=True)
    ranked_scores = []
    for i, score in enumerate(scores, start=1):
        ranked_scores.append(
            score.model_copy(update={"rank": i, "narrative": build_narrative(score.factors, i)})
        )
    return ranked_scores
