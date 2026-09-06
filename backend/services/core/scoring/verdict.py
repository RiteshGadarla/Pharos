"""Case verdict assignment. See PLAN.md section 12, "Verdict assignment".

Three outcome classes, and the third is the reason this module exists:

  ATTRIBUTED      one vessel dominates. A prosecutable evidence package.
  RANKED          several plausible candidates, no dominant one. An
                  ordered list with reasons plus the full elimination
                  log, which narrows the field for an investigator.
  DARK_CONFIRMED  every broadcasting vessel was eliminated or scored
                  below the floor, AND at least one unmatched ship
                  target sits inside the origin field. A vessel absent
                  from the AIS picture was present in the origin
                  envelope: radar saw a hull, AIS did not report it.

DARK_CONFIRMED is not a failure state. Every competing system treats
"no broadcasting suspect found" as no result. For an intelligence
organisation it is the finding, and the dossier renders it as a
positive result with the unmatched target's position, size and the
origin probability at that cell.
"""

from __future__ import annotations

from services.core.crosscheck.radar import RadarCrossCheck
from services.core.schemas import CaseVerdict, SuspectScore

DEFAULT_DOMINANCE_MARGIN = 1.5
DEFAULT_DARK_FLOOR = 0.0
DEFAULT_EPS = 1e-6


def _was_broadcasting_throughout(mmsi: str, vessels_with_dark_gaps: set[str]) -> bool:
    return mmsi not in vessels_with_dark_gaps


def assign_verdict(
    case_id: str,
    scores: list[SuspectScore],
    cross_check: RadarCrossCheck | None,
    vessels_with_dark_gaps: set[str],
    verdict_config: dict,
    infrastructure_flag: bool = False,
) -> CaseVerdict:
    """Assigns one of the three classes.

    Order matters. DARK_CONFIRMED is tested first, because its condition
    is the strictest: it requires both that no broadcasting vessel is a
    plausible candidate and that radar independently saw something in
    the origin envelope. A case that satisfies both is not a weak
    RANKED, it is a different finding.
    """
    dominance_margin = float(verdict_config.get("dominance_margin", DEFAULT_DOMINANCE_MARGIN))
    dark_floor = float(verdict_config.get("dark_floor", DEFAULT_DARK_FLOOR))
    eps = float(verdict_config.get("eps", DEFAULT_EPS))

    unmatched_in_field = cross_check.unmatched_in_field(eps) if cross_check else []
    ranked = sorted(scores, key=lambda s: s.rank)
    plausible = [s for s in ranked if s.total > dark_floor]

    if not plausible and unmatched_in_field:
        targets = ", ".join(
            f"{t.target_id} at {t.centroid[1]:.4f}, {t.centroid[0]:.4f} ({t.pixel_area} px)"
            for t in unmatched_in_field
        )
        return CaseVerdict(
            case_id=case_id,
            verdict="DARK_CONFIRMED",
            reasoning=(
                "No broadcasting vessel survived elimination with a score above the "
                f"plausibility floor of {dark_floor:.2f}, and the SAR scene contains "
                f"{len(unmatched_in_field)} ship target(s) with no AIS association sitting "
                f"inside the origin probability field: {targets}. Radar photographed a hull "
                "that AIS did not report, inside the envelope the spill could have started "
                "in. This is a positive finding, not an absence of one. It is not an "
                "identification: an unmatched target may be a vessel below AIS carriage "
                "requirements, a fishing craft or a buoy, and Sentinel-1 misses small "
                "vessels at GRD resolution."
            ),
            top_suspects=[s.mmsi for s in ranked[:3]],
            unmatched_targets=[t.target_id for t in unmatched_in_field],
            infrastructure_flag=infrastructure_flag,
        )

    if not ranked:
        return CaseVerdict(
            case_id=case_id,
            verdict="RANKED",
            reasoning=(
                "Every vessel in the window was eliminated by a structural rule, and no "
                "unmatched radar target sits inside the origin field. The elimination log "
                "records the rule and the reason for each vessel. Nothing here supports a "
                "suspect, and the honest reading is that the traffic picture for this "
                "window is incomplete."
            ),
            top_suspects=[],
            unmatched_targets=[t.target_id for t in (cross_check.unmatched if cross_check else [])],
            infrastructure_flag=infrastructure_flag,
        )

    top = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    margin = (top.total - runner_up.total) if runner_up else float("inf")
    broadcasting = _was_broadcasting_throughout(top.mmsi, vessels_with_dark_gaps)

    if margin >= dominance_margin and broadcasting:
        return CaseVerdict(
            case_id=case_id,
            verdict="ATTRIBUTED",
            reasoning=(
                f"{top.mmsi} outscores the next candidate by {margin:.2f}, above the "
                f"dominance margin of {dominance_margin:.2f}, and was broadcasting "
                "throughout the origin window, so its track is complete rather than "
                "reconstructed across a gap. This is a ranked evidence package for a human "
                "investigator, not an automated accusation."
            ),
            top_suspects=[s.mmsi for s in ranked[:3]],
            unmatched_targets=[t.target_id for t in unmatched_in_field],
            infrastructure_flag=infrastructure_flag,
        )

    if margin >= dominance_margin and not broadcasting:
        reason_tail = (
            f"{top.mmsi} leads by {margin:.2f}, but it went dark inside the origin window, "
            "so part of its track is a dead-reckoned reconstruction rather than an "
            "observation. The lead is real and the gap is why this is not stated as a "
            "single attribution."
        )
    else:
        reason_tail = (
            f"The leading candidate's margin over the next is {margin:.2f}, below the "
            f"dominance margin of {dominance_margin:.2f}. Several vessels remain plausible."
        )

    return CaseVerdict(
        case_id=case_id,
        verdict="RANKED",
        reasoning=(
            reason_tail
            + " The ranked list, the factor breakdown behind each score, and the full "
            "elimination log together narrow the field for an investigator."
        ),
        top_suspects=[s.mmsi for s in ranked[:3]],
        unmatched_targets=[t.target_id for t in unmatched_in_field],
        infrastructure_flag=infrastructure_flag,
    )
