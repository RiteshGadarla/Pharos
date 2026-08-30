"""Elimination rules, applied before scoring. See PLAN.md section 10.

Nothing here eliminates on vessel type or any weak-evidence factor,
only these three structural checks. Everything else downweights inside
scoring/engine.py instead. Every rule fires with a human-readable
reason from config/scoring.yaml, never a bare error code.
"""

from __future__ import annotations

import datetime

import pandas as pd
import xarray as xr

from services.core.ais.tracks import position_at
from services.core.schemas import AISTrack, Elimination


def _field_time_bounds(field_ds: xr.Dataset) -> tuple[datetime.datetime, datetime.datetime]:
    times = field_ds["time"].values
    return pd.Timestamp(times.min()).to_pydatetime(), pd.Timestamp(times.max()).to_pydatetime()


def _has_spatial_support(track: AISTrack, field_ds: xr.Dataset, eps: float) -> bool:
    from shapely.geometry import shape

    from services.core.scoring.factors import field_mass_in_polygon, sample_field_at

    for t in [pd.Timestamp(x).to_pydatetime() for x in field_ds["time"].values]:
        pos = position_at(track, t)
        if pos is not None and sample_field_at(field_ds, pos[0], pos[1], t) > eps:
            return True

    field_t_min, field_t_max = _field_time_bounds(field_ds)
    for gap in track.dark_gaps:
        overlap_start = max(gap.start, field_t_min)
        overlap_end = min(gap.end, field_t_max)
        if overlap_start > overlap_end:
            continue
        polygon = shape(gap.envelope)
        for t in [pd.Timestamp(x).to_pydatetime() for x in field_ds["time"].values]:
            if overlap_start <= t <= overlap_end and field_mass_in_polygon(field_ds, polygon, t) > eps:
                return True
    return False


def check_elimination(track: AISTrack, field_ds: xr.Dataset, scoring_config: dict) -> Elimination | None:
    """Returns an Elimination if any rule fires, otherwise None. Checked
    in order: no temporal overlap, insufficient track, no spatial
    support, matching PLAN.md section 10's list."""
    elim_cfg = scoring_config["elimination"]
    field_t_min, field_t_max = _field_time_bounds(field_ds)

    if not track.points:
        cfg = elim_cfg["no_temporal_overlap"]
        return Elimination(mmsi=track.mmsi, reason=cfg["reason"], rule=cfg["rule"])

    track_t_min = track.points[0].ts
    track_t_max = track.points[-1].ts
    if track_t_max < field_t_min or track_t_min > field_t_max:
        cfg = elim_cfg["no_temporal_overlap"]
        return Elimination(mmsi=track.mmsi, reason=cfg["reason"], rule=cfg["rule"])

    n_pings_in_window = sum(1 for p in track.points if field_t_min <= p.ts <= field_t_max)
    if n_pings_in_window < elim_cfg["insufficient_track"]["min_pings"]:
        cfg = elim_cfg["insufficient_track"]
        return Elimination(mmsi=track.mmsi, reason=cfg["reason"], rule=cfg["rule"])

    eps = elim_cfg["no_spatial_support"]["eps"]
    if not _has_spatial_support(track, field_ds, eps):
        cfg = elim_cfg["no_spatial_support"]
        return Elimination(mmsi=track.mmsi, reason=cfg["reason"], rule=cfg["rule"])

    return None


def eliminate_and_survive(
    tracks: list[AISTrack], field_ds: xr.Dataset, scoring_config: dict
) -> tuple[list[AISTrack], list[Elimination]]:
    """Splits tracks into (survivors, eliminations). Survivors go on to
    scoring/engine.py; eliminations are a first-class output on their
    own, per non-negotiable 2, never a debug artifact."""
    survivors: list[AISTrack] = []
    eliminations: list[Elimination] = []
    for track in tracks:
        elimination = check_elimination(track, field_ds, scoring_config)
        if elimination is not None:
            eliminations.append(elimination)
        else:
            survivors.append(track)
    return survivors, eliminations
