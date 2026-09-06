"""The AIS completeness record. See PLAN.md section 18.

One row per processed scene, measuring how much of the AIS picture the
radar image does not corroborate: how many hulls the SAR scene showed,
how many of those AIS accounted for, and how big the ones it did not
are.

Like the dark period ledger, this is deliberately not analytics. The
value is that it exists and accumulates across runs. A single scene's
unmatched count means little; a year of them is a measurement of AIS
coverage in a region that nobody currently has.
"""

from __future__ import annotations

import datetime
import json
import os
from dataclasses import asdict, dataclass, field as dataclass_field

from services.core.crosscheck.radar import RadarCrossCheck

DEFAULT_LEDGER_PATH = "data/processed/ais_completeness.jsonl"


@dataclass(frozen=True)
class CompletenessRow:
    scene_id: str
    acquired_at: str
    footprint: list[float]  # minlon, minlat, maxlon, maxlat
    sensor: str
    n_targets: int
    n_matched: int
    n_unmatched: int
    # Pixel areas of the unmatched targets, so the record carries the
    # size distribution rather than just a count. A scene full of tiny
    # unmatched targets is a fishing fleet; one large unmatched target
    # in an origin envelope is a different thing entirely.
    unmatched_pixel_areas: list[int] = dataclass_field(default_factory=list)
    case_id: str | None = None

    @property
    def matched_fraction(self) -> float:
        return self.n_matched / self.n_targets if self.n_targets else 0.0


def build_row(
    scene_id: str,
    acquired_at: datetime.datetime,
    footprint: tuple[float, float, float, float],
    sensor: str,
    cross_check: RadarCrossCheck,
    case_id: str | None = None,
) -> CompletenessRow:
    return CompletenessRow(
        scene_id=scene_id,
        acquired_at=acquired_at.isoformat(),
        footprint=[float(v) for v in footprint],
        sensor=sensor,
        n_targets=len(cross_check.targets),
        n_matched=len(cross_check.matched),
        n_unmatched=len(cross_check.unmatched),
        unmatched_pixel_areas=sorted(t.pixel_area for t in cross_check.unmatched),
        case_id=case_id,
    )


def append_row(row: CompletenessRow, path: str = DEFAULT_LEDGER_PATH) -> None:
    """Appends one scene's record. Append-only JSON Lines, for the same
    reasons as ledger/dark.py: it survives a demo with the database
    stopped, and the flat row maps onto a table with no translation."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(asdict(row)) + "\n")


def read_rows(path: str = DEFAULT_LEDGER_PATH) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]
