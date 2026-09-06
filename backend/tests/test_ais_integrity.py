"""Tests for AIS integrity flags, factor F7. See PLAN.md section 10.

F7 exists so that "AIS can be spoofed, not just switched off" is
answered with a factor rather than a shrug. These tests hold it to two
things: it fires on the anomalies it claims to detect, and it stays
silent on an ordinary clean track, because a factor that flags everyone
separates nobody.
"""

from __future__ import annotations

import datetime

import numpy as np
import xarray as xr
import yaml

from services.core.ais.integrity import annotate_integrity, check_mmsi_reuse
from services.core.schemas import AISPoint, AISTrack
from services.core.scoring.factors import NEUTRAL_FACTOR, compute_ais_integrity

T0 = datetime.datetime(2026, 1, 15, 0, 0)


def _config() -> dict:
    with open("config/scoring.yaml") as f:
        return yaml.safe_load(f).get("integrity", {})


def _clean_track(mmsi: str = "419000001") -> AISTrack:
    """Ten minutes between pings at 10 knots, positions consistent with
    the reported speed. Nothing here should fire anything."""
    points = []
    lat = 17.0
    for i in range(6):
        points.append(
            AISPoint(
                ts=T0 + datetime.timedelta(minutes=10 * i),
                lat=lat + i * (10 * 1.852 / 6) / 111.32,
                lon=68.0,
                sog=10.0,
                cog=0.0,
            )
        )
    return AISTrack(mmsi=mmsi, vessel_type="cargo", points=points)


def _field(t_min: datetime.datetime, t_max: datetime.datetime) -> xr.Dataset:
    n = 5
    times = np.array(
        [t_min + (t_max - t_min) * i / (n - 1) for i in range(n)], dtype="datetime64[ns]"
    )
    field = np.ones((n, 2, 2))
    field = field / field.sum()
    return xr.Dataset(
        {"probability": (("time", "lat", "lon"), field)},
        coords={"time": times, "lat": [16.99, 17.01], "lon": [67.99, 68.01]},
        attrs={"seed": 1, "n_members": 1},
    )


def test_a_clean_track_raises_no_flags():
    annotated = annotate_integrity([_clean_track()], _config())
    assert annotated[0].integrity_flags == []


def test_implied_speed_fires_on_an_impossible_jump():
    track = _clean_track()
    points = list(track.points)
    points[3] = points[3].model_copy(update={"lat": points[3].lat + 2.0})  # ~220 km in 10 minutes
    flagged = annotate_integrity([track.model_copy(update={"points": points})], _config())
    kinds = {f.kind for f in flagged[0].integrity_flags}
    assert "implied_speed" in kinds


def test_position_jump_fires_when_movement_contradicts_reported_speed():
    """Distinct from implied_speed: the distance is coverable, but the
    vessel's own reported speed says it went somewhere else. That
    mismatch between self-reported dynamics and self-reported positions
    is the signature of a fabricated track."""
    points = [
        AISPoint(ts=T0, lat=17.0, lon=68.0, sog=1.0, cog=0.0),
        AISPoint(ts=T0 + datetime.timedelta(hours=1), lat=17.15, lon=68.0, sog=1.0, cog=0.0),
    ]
    track = AISTrack(mmsi="419000001", vessel_type="cargo", points=points)
    flagged = annotate_integrity([track], _config())
    kinds = {f.kind for f in flagged[0].integrity_flags}
    assert "position_jump" in kinds
    assert "implied_speed" not in kinds  # 16 km in an hour is only ~9 knots


def test_mmsi_reuse_is_only_visible_across_the_fleet():
    """Two hulls sharing one MMSI cannot be seen in either track alone,
    which is why this check runs over the whole set."""
    a = AISTrack(
        mmsi="419000001", vessel_type="cargo",
        points=[AISPoint(ts=T0, lat=17.0, lon=68.0, sog=10.0, cog=0.0)],
    )
    b = AISTrack(
        mmsi="419000001", vessel_type="cargo",
        points=[AISPoint(ts=T0 + datetime.timedelta(minutes=5), lat=20.0, lon=72.0, sog=10.0, cog=0.0)],
    )
    flags = check_mmsi_reuse([a, b], _config())
    assert "419000001" in flags
    assert flags["419000001"][0].kind == "mmsi_reuse"


def test_no_imo_only_fires_for_classes_that_should_carry_one():
    config = _config()
    tanker = _clean_track("419000001").model_copy(update={"vessel_type": "tanker"})
    fishing = _clean_track("419000002").model_copy(update={"vessel_type": "fishing"})
    flagged = annotate_integrity([tanker, fishing], config, imo_by_mmsi={})
    by_mmsi = {t.mmsi: t for t in flagged}
    assert any(f.kind == "no_imo" for f in by_mmsi["419000001"].integrity_flags)
    assert not any(f.kind == "no_imo" for f in by_mmsi["419000002"].integrity_flags)


def test_f7_is_neutral_for_a_vessel_with_no_flags():
    """A clean AIS record is the ordinary case. It must contribute
    nothing, not count as evidence of innocence, because the factor is
    combined in log-odds space where anything below 0.5 is a penalty."""
    track = _clean_track()
    field_ds = _field(track.points[0].ts, track.points[-1].ts)
    assert compute_ais_integrity(track, field_ds) == NEUTRAL_FACTOR


def test_f7_grows_with_more_flags_but_saturates_below_one():
    """Noisy-or: two independent flags raise suspicion more than one,
    but ten flags of the same kind must not run away to certainty."""
    track = _clean_track()
    field_ds = _field(track.points[0].ts, track.points[-1].ts)

    from services.core.schemas import IntegrityFlag

    one = track.model_copy(
        update={"integrity_flags": [IntegrityFlag(kind="no_imo", at=track.points[1].ts, detail="d", severity=0.3)]}
    )
    two = track.model_copy(
        update={
            "integrity_flags": [
                IntegrityFlag(kind="no_imo", at=track.points[1].ts, detail="d", severity=0.3),
                IntegrityFlag(kind="position_jump", at=track.points[2].ts, detail="d", severity=0.7),
            ]
        }
    )
    score_one = compute_ais_integrity(one, field_ds)
    score_two = compute_ais_integrity(two, field_ds)
    assert score_one < score_two < 1.0


def test_flags_outside_the_origin_window_do_not_count():
    """A vessel's reporting problem last Tuesday is not evidence about
    this spill."""
    from services.core.schemas import IntegrityFlag

    track = _clean_track()
    field_ds = _field(track.points[0].ts, track.points[-1].ts)
    stale = track.model_copy(
        update={
            "integrity_flags": [
                IntegrityFlag(
                    kind="position_jump",
                    at=track.points[0].ts - datetime.timedelta(days=7),
                    detail="d",
                    severity=0.9,
                )
            ]
        }
    )
    assert compute_ais_integrity(stale, field_ds) == NEUTRAL_FACTOR
