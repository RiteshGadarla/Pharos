"""Physical validation of the drift engine against real drifters.
See PLAN.md section 17.3.

This is the only component of the system where real ground truth
actually exists, so it is the only place a containment number can be
honestly reported. It answers "your hindcast is unvalidated" with a
real measurement instead of an argument.

Method: take a NOAA Global Drifter Program buoy's known position at
time t1, run the backward ensemble from it over a 24 to 48 hour
horizon, and check whether the drifter's actual known position at t0
falls inside the resulting probability field, and at what quantile.
Repeat over N segments and report the containment rate and the median
quantile of the true position.

There is Indian precedent for the method: INCOIS and the Indian Coast
Guard ran a Surface Velocity Program drifter experiment at Mumbai High
to evaluate their operational oil spill trajectory model.

The honest caveat, which goes in the report and not just here: a
drifter is not oil. It does not weather, it does not spread as a film,
and it does not carry the wind drift factor uncertainty a surface slick
does. This validates the advection and diffusion core of the hindcast,
not the oil model on top of it.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field as dataclass_field

import numpy as np
import xarray as xr

from services.core.hindcast.ensemble import run_ensemble
from services.core.hindcast.field import build_origin_field
from services.core.schemas import Detection

CAVEAT = (
    "A drifter is not oil: it does not weather, does not spread as a surface film, and "
    "does not carry the wind drift factor uncertainty a slick does. This validates the "
    "advection and diffusion core of the hindcast, not the oil model on top of it."
)

PRECEDENT = (
    "Method precedent: INCOIS and the Indian Coast Guard conducted a Surface Velocity "
    "Program drifter experiment at Mumbai High to evaluate their operational oil spill "
    "trajectory model."
)


@dataclass(frozen=True)
class DrifterSegment:
    """One buoy over one interval: where it was at t1, where it actually
    was at t0, and how far back that is."""

    drifter_id: str
    t0: datetime.datetime
    t1: datetime.datetime
    lat_t0: float
    lon_t0: float
    lat_t1: float
    lon_t1: float

    @property
    def horizon_hours(self) -> float:
        return (self.t1 - self.t0).total_seconds() / 3600.0


@dataclass
class SegmentResult:
    segment: DrifterSegment
    contained: bool
    quantile: float  # what fraction of the field's mass sits below the true position's cell
    probability_at_truth: float


@dataclass
class DrifterReport:
    results: list[SegmentResult] = dataclass_field(default_factory=list)

    @property
    def containment_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.contained) / len(self.results)

    @property
    def median_quantile(self) -> float | None:
        if not self.results:
            return None
        return float(np.median([r.quantile for r in self.results]))


def parse_gdp_records(rows: list[dict], max_segments: int, horizon_hours: float) -> list[DrifterSegment]:
    """Turns Global Drifter Program rows into segments.

    Rows are dicts with drifter_id, ts (datetime), lat and lon. Pairing
    is by nearest available observation to t1 minus the horizon, so a
    six-hourly interpolated product and an hourly one both work without
    the caller resampling first.
    """
    by_id: dict[str, list[dict]] = {}
    for row in rows:
        by_id.setdefault(row["drifter_id"], []).append(row)

    segments: list[DrifterSegment] = []
    for drifter_id, observations in by_id.items():
        ordered = sorted(observations, key=lambda r: r["ts"])
        for i, later in enumerate(ordered):
            target_t0 = later["ts"] - datetime.timedelta(hours=horizon_hours)
            earlier = min(
                ordered[:i] or [ordered[0]],
                key=lambda r: abs((r["ts"] - target_t0).total_seconds()),
            )
            if earlier["ts"] >= later["ts"]:
                continue
            segments.append(
                DrifterSegment(
                    drifter_id=drifter_id,
                    t0=earlier["ts"],
                    t1=later["ts"],
                    lat_t0=float(earlier["lat"]),
                    lon_t0=float(earlier["lon"]),
                    lat_t1=float(later["lat"]),
                    lon_t1=float(later["lon"]),
                )
            )
            if len(segments) >= max_segments:
                return segments
    return segments


def _seed_polygon(lat: float, lon: float, half_width_deg: float = 0.01) -> dict:
    """A small box around the drifter's known position at t1.

    A box rather than a point because the ensemble seeds particles
    inside a polygon, and because a real slick is never a point either.
    Its width is the position uncertainty being asserted, so keep it
    small and state it.
    """
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon - half_width_deg, lat - half_width_deg],
                [lon - half_width_deg, lat + half_width_deg],
                [lon + half_width_deg, lat + half_width_deg],
                [lon + half_width_deg, lat - half_width_deg],
                [lon - half_width_deg, lat - half_width_deg],
            ]
        ],
    }


def quantile_of_position(field_ds: xr.Dataset, lat: float, lon: float, t: datetime.datetime) -> tuple[float, float]:
    """(quantile, probability) of a true position within the field.

    The quantile is the fraction of the field's total mass held by cells
    with probability at or below this one, so 0.95 means the true
    position landed in the densest 5 percent of the field. That is the
    number worth reporting: a field wide enough to contain everything
    contains the truth too, and only the quantile distinguishes a
    genuinely sharp hindcast from a usefully vague one.
    """
    slice_ds = field_ds["probability"].sel(time=np.datetime64(t), method="nearest")
    values = slice_ds.values
    total = float(values.sum())
    if total <= 0:
        return 0.0, 0.0
    p = float(slice_ds.sel(lat=lat, lon=lon, method="nearest").values)
    below = float(values[values <= p].sum())
    return below / total, p


def validate_segment(
    segment: DrifterSegment,
    current_path: str,
    wind_path: str,
    pipeline_config: dict,
    containment_eps: float = 1e-9,
) -> SegmentResult:
    """Runs one backward ensemble from the drifter's t1 position and
    checks where its real t0 position landed in the resulting field."""
    detection = Detection(
        detection_id=f"drifter-{segment.drifter_id}-{int(segment.t1.timestamp())}",
        scene_id=f"GDP-{segment.drifter_id}",
        class_name="oil",  # the schema's vocabulary; this is a drifter, not a slick
        geometry=_seed_polygon(segment.lat_t1, segment.lon_t1),
        mean_class_prob=1.0,
        pixel_area=1,
    )
    hindcast_cfg = dict(pipeline_config["hindcast"])
    hindcast_cfg["backward_horizon_hours"] = segment.horizon_hours
    config = {"seed": pipeline_config["seed"], "hindcast": hindcast_cfg}

    member_results = run_ensemble(detection, current_path, wind_path, segment.t1, config)
    field_ds = build_origin_field(
        member_results,
        grid_resolution_deg=hindcast_cfg["field"]["grid_resolution_deg"],
        time_step_minutes=hindcast_cfg["field"]["time_step_minutes"],
        gaussian_bandwidth_deg=hindcast_cfg["field"]["gaussian_bandwidth_deg"],
        seed=config["seed"],
        kernel=hindcast_cfg.get("kernel", "openoil"),
    )

    quantile, probability = quantile_of_position(field_ds, segment.lat_t0, segment.lon_t0, segment.t0)
    return SegmentResult(
        segment=segment,
        contained=probability > containment_eps,
        quantile=quantile,
        probability_at_truth=probability,
    )


def render_markdown(report: DrifterReport) -> str:
    """The drifter validation section, as it goes into validation.md."""
    lines = [
        "## Physical validation of the drift engine (NOAA Global Drifter Program)",
        "",
        CAVEAT,
        "",
        PRECEDENT,
        "",
    ]
    if not report.results:
        lines += [
            "No drifter segments were run. This section is empty because the Global Drifter",
            "Program trajectories have not been fetched, not because containment was zero.",
            "",
        ]
        return "\n".join(lines)

    lines += [
        f"Segments run: {len(report.results)}",
        f"Containment rate (true prior position falls inside the field): "
        f"{report.containment_rate:.1%}",
        f"Median quantile of the true position: {report.median_quantile:.3f} "
        "(1.0 would mean the truth landed on the field's densest cell every time)",
        "",
        "| drifter | horizon (h) | contained | quantile |",
        "|---|---|---|---|",
    ]
    for r in report.results:
        lines.append(
            f"| `{r.segment.drifter_id}` | {r.segment.horizon_hours:.0f} | "
            f"{'yes' if r.contained else 'no'} | {r.quantile:.3f} |"
        )
    lines.append("")
    return "\n".join(lines)
