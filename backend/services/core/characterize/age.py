"""Relative slick age banding. See PLAN.md section 7.

Absolute slick age in hours cannot be estimated reliably from a single
SAR acquisition. This module reports a relative band and states its
reasoning, never a number in hours: that line goes in the README and
the dossier verbatim.
"""

from __future__ import annotations

from services.core.schemas import SlickFeatures

FRESH_CONTRAST_DB = -8.0
FRESH_COMPLEXITY_MAX = 1.5
WEATHERED_COMPLEXITY_MIN = 2.5


def classify_age(contrast_db: float, complexity_ratio: float) -> tuple[str, str]:
    """Returns (age_band, age_reasoning).

    Fresh slicks are high contrast (strongly negative contrast_db, since
    oil damps backscatter relative to the surrounding sea) and compact
    (low complexity_ratio, 1.0 is a circle). Weathered slicks are lower
    contrast and fragmented by wind and current action, so they have a
    high complexity_ratio. Anything else is intermediate.
    """
    if contrast_db <= FRESH_CONTRAST_DB and complexity_ratio <= FRESH_COMPLEXITY_MAX:
        return (
            "fresh",
            f"Contrast {contrast_db:.1f} dB is at or below {FRESH_CONTRAST_DB:.1f} dB "
            f"and complexity ratio {complexity_ratio:.2f} is at or below "
            f"{FRESH_COMPLEXITY_MAX:.2f}: a compact, high-contrast slick, "
            "consistent with a recent discharge.",
        )
    if contrast_db > FRESH_CONTRAST_DB and complexity_ratio >= WEATHERED_COMPLEXITY_MIN:
        return (
            "weathered",
            f"Contrast {contrast_db:.1f} dB is above {FRESH_CONTRAST_DB:.1f} dB and "
            f"complexity ratio {complexity_ratio:.2f} is at or above "
            f"{WEATHERED_COMPLEXITY_MIN:.2f}: a fragmented, lower-contrast slick, "
            "consistent with wind and current weathering over time.",
        )
    return (
        "intermediate",
        f"Contrast {contrast_db:.1f} dB and complexity ratio {complexity_ratio:.2f} "
        "fall between the fresh and weathered rules: neither a compact "
        "high-contrast slick nor a fragmented low-contrast one.",
    )


def with_age(features: dict) -> SlickFeatures:
    """Merges the age classification into a features dict and returns the
    completed SlickFeatures model."""
    age_band, age_reasoning = classify_age(features["contrast_db"], features["complexity_ratio"])
    return SlickFeatures(**features, age_band=age_band, age_reasoning=age_reasoning)
