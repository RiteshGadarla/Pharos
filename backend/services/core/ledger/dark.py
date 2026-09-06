"""The dark period ledger. See PLAN.md section 18.

One row per DarkGap ever detected, independent of whether oil was
involved in that case. This is the by-product that outlives any single
case: over time it becomes a record of AIS denial behaviour, which is
worth having whether or not any individual gap turns out to matter.

It is deliberately not analytics. The value is that it exists and
accumulates. Do not build dashboards, alerting or scoring on top of it.
"""

from __future__ import annotations

import datetime
import json
import os
from dataclasses import asdict, dataclass

from services.core.crosscheck.radar import RadarCrossCheck
from services.core.schemas import AISTrack

DEFAULT_LEDGER_PATH = "data/processed/dark_period_ledger.jsonl"


@dataclass(frozen=True)
class DarkPeriodRow:
    mmsi: str
    vessel_type: str
    start: str
    end: str
    duration_min: float
    entry_lon: float
    entry_lat: float
    exit_lon: float
    exit_lat: float
    resumed_course_deg: float | None
    scene_id: str
    case_id: str
    # Whether an unmatched SAR ship target fell inside this gap's
    # dead-reckoned envelope. This is the column that makes the ledger
    # more than a list of dropouts.
    unmatched_target_in_envelope: bool
    unmatched_target_id: str | None


def _resumed_course(track: AISTrack, gap_end: datetime.datetime) -> float | None:
    """The course the vessel reported on its first ping after the gap.
    A vessel that resumes on a materially different heading is the
    behaviour the ledger is worth recording."""
    after = [p for p in track.points if p.ts >= gap_end]
    return float(after[0].cog) if after else None


def build_rows(
    tracks: list[AISTrack],
    scene_id: str,
    case_id: str,
    cross_check: RadarCrossCheck | None = None,
) -> list[DarkPeriodRow]:
    rows: list[DarkPeriodRow] = []
    for track in tracks:
        for gap in track.dark_gaps:
            target_id = None
            if cross_check is not None:
                target, _ = cross_check.support_for(track.mmsi)
                target_id = target.target_id if target else None
            rows.append(
                DarkPeriodRow(
                    mmsi=track.mmsi,
                    vessel_type=track.vessel_type,
                    start=gap.start.isoformat(),
                    end=gap.end.isoformat(),
                    duration_min=gap.duration_min,
                    entry_lon=gap.entry_point[0],
                    entry_lat=gap.entry_point[1],
                    exit_lon=gap.exit_point[0],
                    exit_lat=gap.exit_point[1],
                    resumed_course_deg=_resumed_course(track, gap.end),
                    scene_id=scene_id,
                    case_id=case_id,
                    unmatched_target_in_envelope=target_id is not None,
                    unmatched_target_id=target_id,
                )
            )
    return rows


def append_rows(rows: list[DarkPeriodRow], path: str = DEFAULT_LEDGER_PATH) -> int:
    """Appends to a JSON Lines file.

    JSONL rather than the database, for now, because the ledger has to
    survive a demo run with Postgres stopped, and because append-only
    is the honest shape for a record that is never edited. The row
    schema is flat so it maps onto a table with no translation when the
    database is wired in.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as f:
        for row in rows:
            f.write(json.dumps(asdict(row)) + "\n")
    return len(rows)


def read_rows(path: str = DEFAULT_LEDGER_PATH) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]
