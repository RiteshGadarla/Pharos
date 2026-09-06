"""Tests for the accumulating ledgers. See PLAN.md sections 18 and 19
(phase P12: "both accumulate across two runs, exposed read only").

Accumulation is the only property that matters here. A ledger that
overwrites on each run is a status display, and a status display is not
what section 18 asks for: the value is precisely that these outlive any
single case.
"""

from __future__ import annotations

import datetime

from services.core.crosscheck.radar import RadarCrossCheck
from services.core.ledger import completeness, dark
from services.core.schemas import AISPoint, AISTrack, DarkGap, ShipTarget

T0 = datetime.datetime(2026, 1, 15, 0, 0)


def _envelope(lat: float, lon: float, half: float = 0.01) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon - half, lat - half],
                [lon - half, lat + half],
                [lon + half, lat + half],
                [lon + half, lat - half],
                [lon - half, lat - half],
            ]
        ],
    }


def _dark_track(mmsi: str = "419000001") -> AISTrack:
    points = [
        AISPoint(ts=T0, lat=17.0, lon=68.0, sog=10.0, cog=45.0),
        AISPoint(ts=T0 + datetime.timedelta(minutes=90), lat=17.02, lon=68.02, sog=10.0, cog=120.0),
    ]
    gap = DarkGap(
        start=points[0].ts,
        end=points[1].ts,
        duration_min=90.0,
        entry_point=(points[0].lon, points[0].lat),
        exit_point=(points[1].lon, points[1].lat),
        envelope=_envelope(17.01, 68.01),
    )
    return AISTrack(mmsi=mmsi, vessel_type="cargo", points=points, dark_gaps=[gap])


def _cross_check(unmatched: bool) -> RadarCrossCheck:
    if not unmatched:
        return RadarCrossCheck(targets=[], matched=[], unmatched=[])
    target = ShipTarget(
        target_id="t-1", scene_id="s", centroid=(68.01, 17.01), pixel_area=64, mean_backscatter_db=-4.0
    )
    return RadarCrossCheck(
        targets=[target],
        matched=[],
        unmatched=[target],
        envelope_hits={"t-1": ["419000001"]},
        field_mass={"t-1": 0.02},
    )


def test_dark_ledger_records_the_resumed_course(tmp_path):
    path = str(tmp_path / "dark.jsonl")
    rows = dark.build_rows([_dark_track()], "SCENE-1", "CASE-1")
    dark.append_rows(rows, path)
    written = dark.read_rows(path)
    assert len(written) == 1
    assert written[0]["resumed_course_deg"] == 120.0
    assert written[0]["duration_min"] == 90.0


def test_dark_ledger_records_whether_radar_backed_the_gap(tmp_path):
    """The column that makes this more than a list of dropouts."""
    path = str(tmp_path / "dark.jsonl")
    dark.append_rows(dark.build_rows([_dark_track()], "S", "C", _cross_check(unmatched=True)), path)
    dark.append_rows(dark.build_rows([_dark_track()], "S", "C", _cross_check(unmatched=False)), path)
    rows = dark.read_rows(path)
    assert rows[0]["unmatched_target_in_envelope"] is True
    assert rows[0]["unmatched_target_id"] == "t-1"
    assert rows[1]["unmatched_target_in_envelope"] is False


def test_dark_ledger_accumulates_across_runs(tmp_path):
    path = str(tmp_path / "dark.jsonl")
    dark.append_rows(dark.build_rows([_dark_track("419000001")], "SCENE-1", "CASE-1"), path)
    dark.append_rows(dark.build_rows([_dark_track("419000002")], "SCENE-2", "CASE-2"), path)
    rows = dark.read_rows(path)
    assert len(rows) == 2
    assert {r["scene_id"] for r in rows} == {"SCENE-1", "SCENE-2"}


def test_completeness_row_carries_the_unmatched_size_distribution(tmp_path):
    """A scene full of tiny unmatched targets is a fishing fleet; one
    large unmatched target in an origin envelope is a different thing
    entirely, and a bare count cannot tell them apart."""
    path = str(tmp_path / "completeness.jsonl")
    row = completeness.build_row(
        "SCENE-1", T0, (67.9, 16.9, 68.1, 17.1), "S1", _cross_check(unmatched=True), case_id="CASE-1"
    )
    completeness.append_row(row, path)
    written = completeness.read_rows(path)
    assert written[0]["unmatched_pixel_areas"] == [64]
    assert written[0]["n_unmatched"] == 1
    assert written[0]["sensor"] == "S1"


def test_completeness_ledger_accumulates_across_runs(tmp_path):
    path = str(tmp_path / "completeness.jsonl")
    for scene_id in ("SCENE-1", "SCENE-2"):
        completeness.append_row(
            completeness.build_row(scene_id, T0, (67.9, 16.9, 68.1, 17.1), "S1", _cross_check(True)),
            path,
        )
    rows = completeness.read_rows(path)
    assert len(rows) == 2
    assert {r["scene_id"] for r in rows} == {"SCENE-1", "SCENE-2"}


def test_reading_a_ledger_that_does_not_exist_yet_is_empty_not_an_error():
    """The endpoints call these on a fresh checkout."""
    assert dark.read_rows("data/processed/does-not-exist.jsonl") == []
    assert completeness.read_rows("data/processed/does-not-exist.jsonl") == []
