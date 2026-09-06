"""The case assembling itself, one class of evidence at a time.

See PLAN.md sections 12 and 22.

Stage 3 used to end at a ranked list. A ranking is a result, and the only
things a room can do with a result are accept it or reject it. It gives
nobody anything to interrogate, and every competing system produces one.

What this system has that a trained attribution model cannot have is an
explicit weighted evidence model with named factors and no learned
parameters (non-negotiable 3). That is not merely a defensibility
property to assert in a slide. It means the case can be taken apart and
put back together in front of the room.

So the ranking is rebuilt here in the order an investigator would
actually gather evidence: who was present, who can be ruled out, who was
in the origin field, who stopped reporting over it, who behaved like a
discharge, what kind of vessel each is, what AIS says about itself, and
finally what a second and independent sensor saw. At each step the
ranking is recomputed with only the evidence gathered so far.

Two outputs matter more than the steps themselves.

`stabilises_at_step` is where the answer stops changing. If the leader is
settled by the time the behavioural factors are in and never moves again,
the conclusion does not hang on any one piece of evidence, and that is a
far stronger claim than a large final margin.

`decisive_factors` names any single factor whose removal changes who
leads. An empty list is the strongest result this module can produce:
no one piece of evidence is carrying the case. A non-empty list is not a
failure to hide, it is the caveat the system owes the room, and it is
reported in exactly the same place with exactly the same prominence.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field as dataclass_field

import numpy as np
from shapely.geometry import shape

from services.core.ais.tracks import position_at
from services.core.schemas import AISTrack, SlickFeatures
from services.core.scoring.engine import score_vessels

KM_PER_DEG = 111.0

# The order evidence is added. Each step adds its factors to everything
# already gathered, so step N's ranking is the ranking on the first N
# steps' evidence.
#
# The order is investigative, not numerical. Presence and elimination
# come first because they define the candidate set and the PS asks for
# irrelevant traffic to be filtered out explicitly. Position before
# behaviour, because where a vessel was is a stronger and less
# interpretable claim than how it was moving. The independent sensor
# comes last, so the room can see how much of the case stands without
# it.
EVIDENCE_STEPS: list[tuple[str, str, str, list[str]]] = [
    ("present", "Everyone in the window", "Who was there at all?", []),
    ("eliminated", "Ruled out, with reasons", "Who can be ruled out, and why?", []),
    ("where", "Where they were", "Whose track passes through the origin field?", ["field_integral"]),
    # Timing gets its own step rather than staying folded into "where".
    # F1 does weight the time axis, but inside an integral over space,
    # which means a room watching the case being built never sees
    # timing move the ranking and cannot question it. As its own step
    # it has its own bar and its own argument. See scoring/temporal.py.
    (
        "when",
        "When they were there",
        "Was each vessel over the origin at an hour that matches how weathered the slick looks?",
        ["temporal_consistency"],
    ),
    ("dark", "When they stopped reporting", "Who went dark over the likely origin?", ["dark_overlap"]),
    (
        "behaviour",
        "How they behaved",
        "Who moved like a vessel discharging rather than transiting?",
        ["axis_alignment", "speed_anomaly", "course_anomaly"],
    ),
    ("vessel", "What kind of vessel", "Could it plausibly carry and discharge oil?", ["vessel_plausibility"]),
    ("integrity", "What AIS says about itself", "Is the vessel's own reporting internally consistent?", ["ais_integrity"]),
    (
        "radar",
        "What radar independently saw",
        "Did a second, independent sensor photograph a hull AIS never reported?",
        ["radar_confirmed_dark"],
    ),
]


@dataclass
class RankRow:
    mmsi: str
    total: float
    rank: int


@dataclass
class CaseStep:
    key: str
    label: str
    question: str
    # Factors this step brought in, and everything gathered up to here.
    factors_added: list[str]
    factors_so_far: list[str]
    ranking: list[RankRow] = dataclass_field(default_factory=list)
    lead: str | None = None
    # Did the leader change when this step's evidence arrived?
    lead_changed: bool = False
    note: str = ""


def _subset_config(scoring_config: dict, factor_names: list[str]) -> dict:
    """A scoring config carrying only the named factors.

    The engine already treats an unweighted factor as switched off, which
    is how the validation harness runs its ablations, so a subset config
    is all that is needed to score on partial evidence. No separate code
    path, which matters: a step that scored through different code from
    the real engine would be a reconstruction of the case rather than the
    case.
    """
    factors = {k: v for k, v in scoring_config.get("factors", {}).items() if k in factor_names}
    return {**scoring_config, "factors": factors}


def _rank_rows(scores) -> list[RankRow]:
    return [RankRow(mmsi=s.mmsi, total=round(float(s.total), 4), rank=s.rank) for s in scores]


def build_case(
    survivors: list[AISTrack],
    eliminations: list,
    field_ds,
    slick_features: SlickFeatures,
    scoring_config: dict,
    cross_check=None,
    acquired_at: datetime.datetime | None = None,
    all_tracks: list[AISTrack] | None = None,
    slick_geometry: dict | None = None,
) -> dict:
    """Rebuilds the ranking step by step and reports where it settles."""
    n_total = len(survivors) + len(eliminations)
    steps: list[CaseStep] = []
    gathered: list[str] = []
    previous_lead: str | None = None

    for key, label, question, adds in EVIDENCE_STEPS:
        gathered = [*gathered, *adds]
        step = CaseStep(
            key=key,
            label=label,
            question=question,
            factors_added=list(adds),
            factors_so_far=list(gathered),
        )

        if key == "present":
            step.note = (
                f"{n_total} vessels held a position inside the origin field's time window. "
                "No evidence has been applied yet."
            )
        elif key == "eliminated":
            step.note = (
                f"{len(eliminations)} ruled out, each against a named rule with a written reason. "
                f"{len(survivors)} remain. Nothing below this point is scored against a vessel "
                "that was never a candidate."
            )
        elif not gathered:
            step.note = "No factors configured for this step."
        else:
            scores = score_vessels(
                survivors,
                field_ds,
                slick_features,
                _subset_config(scoring_config, gathered),
                cross_check=cross_check,
                acquired_at=acquired_at,
            )
            step.ranking = _rank_rows(scores)
            step.lead = scores[0].mmsi if scores else None
            step.lead_changed = previous_lead is not None and step.lead != previous_lead
            step.note = _describe(step, scores, previous_lead)
            previous_lead = step.lead

        steps.append(step)

    scored_steps = [s for s in steps if s.lead is not None]
    final_lead = scored_steps[-1].lead if scored_steps else None

    case = {
        "steps": [_step_to_json(s) for s in steps],
        "final_lead": final_lead,
        "stabilises_at_step": _stabilises_at(scored_steps, final_lead),
        "decisive_factors": _decisive_factors(
            survivors, field_ds, slick_features, scoring_config, cross_check, acquired_at, final_lead
        ),
    }
    case["baselines"] = naive_baselines(
        all_tracks if all_tracks is not None else survivors,
        field_ds,
        slick_geometry,
        acquired_at,
        final_lead,
    )
    case["statement"] = robustness_statement(case)
    return case


def _describe(step: CaseStep, scores, previous_lead: str | None) -> str:
    if not scores:
        return "No vessel survived to be scored on this evidence."
    lead = scores[0]
    if len(scores) == 1:
        return f"{lead.mmsi} is the only candidate remaining."
    margin = lead.total - scores[1].total
    if step.lead_changed:
        return (
            f"This evidence moves {lead.mmsi} ahead of {previous_lead}. "
            f"It now leads by {margin:.2f}."
        )
    return f"{lead.mmsi} still leads, now by {margin:.2f}."


def _stabilises_at(scored_steps: list[CaseStep], final_lead: str | None) -> str | None:
    """The earliest step from which the leader never changes again.

    The number the room should actually care about. A conclusion settled
    early and unmoved by everything after it is robust in a way a large
    final margin does not by itself demonstrate.
    """
    if final_lead is None:
        return None
    for i, step in enumerate(scored_steps):
        if all(later.lead == final_lead for later in scored_steps[i:]):
            return step.key
    return None


def _decisive_factors(
    survivors,
    field_ds,
    slick_features,
    scoring_config: dict,
    cross_check,
    acquired_at,
    final_lead: str | None,
) -> list[str]:
    """Factors whose removal alone changes who leads.

    A leave-one-out ablation over the full evidence set. Empty is the
    strongest possible answer: the case does not rest on any single piece
    of evidence, so disbelieving any one of them does not change who is
    ranked first.
    """
    if final_lead is None:
        return []

    all_factors = list(scoring_config.get("factors", {}).keys())
    decisive: list[str] = []
    for dropped in all_factors:
        remaining = [f for f in all_factors if f != dropped]
        if not remaining:
            continue
        scores = score_vessels(
            survivors,
            field_ds,
            slick_features,
            _subset_config(scoring_config, remaining),
            cross_check=cross_check,
            acquired_at=acquired_at,
        )
        if scores and scores[0].mmsi != final_lead:
            decisive.append(dropped)
    return decisive


# What simpler systems would have concluded.
#
# The step-by-step rebuild shows how this system reached its answer. It
# does not, on its own, show that the answer needed this system. These
# baselines do: each is a real approach that a reasonable person might
# take, computed on the same data, and each is named so the room can see
# exactly what it assumes.
#
# PLAN.md section 17.1 calls the ablations the strongest numbers
# available to the project, and section 22 lists "this is an off the
# shelf model plus OpenDrift" as the first objection a jury will raise.
# This is that argument made on the case in front of them rather than in
# a table of fifty synthetic incidents.
#
# When a baseline agrees, the display says so. A baseline comparison that
# could only ever flatter the system would be worthless.


def _slick_centroid(slick_geometry: dict | None) -> tuple[float, float] | None:
    if not slick_geometry:
        return None
    c = shape(slick_geometry).centroid
    return (c.y, c.x)


def _field_centroid(field_ds) -> tuple[float, float]:
    """Mass-weighted centre of the whole origin field.

    The point the field would collapse to if a system insisted on a
    single origin. Non-negotiable 1 forbids using this for scoring; it
    is computed here only to show what ranking by it produces.
    """
    prob = field_ds["probability"].values
    lats = field_ds["lat"].values
    lons = field_ds["lon"].values
    mass = prob.sum()
    if mass <= 0:
        return (float(lats.mean()), float(lons.mean()))
    lat_w = prob.sum(axis=(0, 2))
    lon_w = prob.sum(axis=(0, 1))
    return (float((lat_w * lats).sum() / mass), float((lon_w * lons).sum() / mass))


def _closest_approach_km(track: AISTrack, lat: float, lon: float) -> float:
    best = float("inf")
    for p in track.points:
        dy = (p.lat - lat) * KM_PER_DEG
        dx = (p.lon - lon) * KM_PER_DEG * np.cos(np.radians(lat))
        best = min(best, float(np.hypot(dx, dy)))
    return best


def naive_baselines(
    all_tracks: list[AISTrack],
    field_ds,
    slick_geometry: dict | None,
    acquired_at: datetime.datetime | None,
    our_answer: str | None,
) -> list[dict]:
    """What three simpler approaches would conclude on this same case."""
    out: list[dict] = []

    slick = _slick_centroid(slick_geometry)
    if slick and acquired_at:
        ranked = []
        for t in all_tracks:
            pos = position_at(t, acquired_at)
            if pos is None:
                continue
            dy = (pos[0] - slick[0]) * KM_PER_DEG
            dx = (pos[1] - slick[1]) * KM_PER_DEG * np.cos(np.radians(slick[0]))
            ranked.append((float(np.hypot(dx, dy)), t.mmsi))
        ranked.sort()
        # The runner-up matters as much as the winner. A baseline that
        # picks the right vessel by half a kilometre out of sixty is not
        # picking it, it is guessing and getting lucky, and reporting the
        # agreement without the margin would credit it with a
        # discrimination it does not have.
        detail = "no vessel had a position"
        if ranked:
            detail = f"{ranked[0][1]} at {ranked[0][0]:.0f} km"
            if len(ranked) > 1:
                detail += f", next at {ranked[1][0]:.0f} km"
        out.append({
            "key": "nearest_now",
            "label": "Nearest vessel when the satellite passed",
            "assumes": "That the oil is where it started. It is not: it has been drifting since the discharge.",
            "answer": ranked[0][1] if ranked else None,
            "detail": detail,
            "separation_km": round(ranked[1][0] - ranked[0][0], 1) if len(ranked) > 1 else None,
            # How far the "nearest" vessel actually was. A baseline can
            # agree with us while its winner sits 64 km from the slick,
            # which is not proximity picking the vessel out, it is
            # proximity having nothing to say and landing on the right
            # answer anyway. Reporting the agreement without this would
            # credit it with a discrimination it does not have.
            "winner_km": round(ranked[0][0], 1) if ranked else None,
        })

    c_lat, c_lon = _field_centroid(field_ds)
    ranked = sorted((_closest_approach_km(t, c_lat, c_lon), t.mmsi) for t in all_tracks)
    centroid_detail = ""
    if ranked:
        centroid_detail = f"{ranked[0][1]} passed {ranked[0][0]:.1f} km from the centroid"
        if len(ranked) > 1:
            centroid_detail += f", next {ranked[1][0]:.1f} km"
    out.append({
        "key": "nearest_centroid",
        "label": "Nearest vessel to the origin field's centre",
        "assumes": (
            "That the origin is a point. It is a probability over space and time, and collapsing it "
            "throws away both the spread and the timing."
        ),
        "answer": ranked[0][1] if ranked else None,
        "detail": centroid_detail,
        "separation_km": round(ranked[1][0] - ranked[0][0], 1) if len(ranked) > 1 else None,
        "winner_km": round(ranked[0][0], 1) if ranked else None,
    })

    dark = [t.mmsi for t in all_tracks if t.dark_gaps]
    out.append({
        "key": "any_dark",
        "label": "Any vessel that went dark",
        "assumes": "That going dark is itself incriminating. Transponders fail, and vessels go dark for many reasons.",
        "answer": dark[0] if len(dark) == 1 else None,
        "detail": (
            f"{len(dark)} vessels went dark ({', '.join(dark)}), so this gives no single answer"
            if len(dark) != 1
            else f"only {dark[0]} went dark"
        ),
        "separation_km": None,
        "winner_km": None,
    })

    for b in out:
        b["agrees"] = b["answer"] is not None and b["answer"] == our_answer
    return out


def _step_to_json(step: CaseStep) -> dict:
    return {
        "key": step.key,
        "label": step.label,
        "question": step.question,
        "factors_added": step.factors_added,
        "factors_so_far": step.factors_so_far,
        "ranking": [{"mmsi": r.mmsi, "total": r.total, "rank": r.rank} for r in step.ranking],
        "lead": step.lead,
        "lead_changed": step.lead_changed,
        "note": step.note,
    }


def robustness_statement(case: dict) -> str:
    """One sentence a presenter can read out, and a jury can hold the
    system to."""
    lead = case.get("final_lead")
    if lead is None:
        return "No vessel survived elimination, so there is no ranking to test."

    decisive = case.get("decisive_factors") or []
    stabilises = case.get("stabilises_at_step")
    where = next((s["label"] for s in case["steps"] if s["key"] == stabilises), None)

    if not decisive:
        settled = f" The ranking settles at {where!r} and does not change again." if where else ""
        return (
            f"{lead} leads on the full evidence, and on every leave-one-out subset of it: "
            f"there is no single factor you could disbelieve that would change who is ranked "
            f"first.{settled}"
        )
    names = ", ".join(decisive)
    return (
        f"{lead} leads on the full evidence, but the result depends on {names}: removing that "
        "alone changes who is ranked first. The ranking should be read with that in mind."
    )
