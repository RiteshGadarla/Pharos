"""Forward drift forecast. See PLAN.md section 15.

Same kernel, same ensemble, same field builder as the backward hindcast,
run with a positive time step from the slick as detected. It answers the
other half of the drift question: not where the oil came from, but where
it is going, which is the response planning product.

Two rules govern this module.

First, the forecast is never an input to attribution. The scoring engine
takes the origin field and nothing else. A vessel is not made more or
less suspicious by where the oil drifts after the satellite saw it, and
wiring the forecast into the score would be a straightforward way to
double count the same physics. `assert_not_scoring_input` exists so that
rule is enforceable rather than merely stated, and a test calls it.

Second, the forward run shares the backward run's seed particles. Both
draw from the same global seed before direction is consulted, so the two
fields meet at the acquisition instant on the same slick rather than
being two independently drifting stories that happen to be drawn on one
map.
"""

from __future__ import annotations

import datetime

import numpy as np
import xarray as xr

from services.core.drift.kernel import DriftKernel
from services.core.hindcast.ensemble import run_ensemble
from services.core.hindcast.field import build_origin_field
from services.core.schemas import Detection

DEFAULT_FORWARD_HORIZON_HOURS = 24.0


def forecast_config(pipeline_config: dict) -> dict:
    """The `forecast:` block, with the horizon defaulted.

    Deliberately not merged into `hindcast:`. A forecast horizon is a
    response planning decision (how far ahead is a responder being asked
    to act) and a hindcast horizon is an evidentiary one (how far back
    the physics still says anything useful). Tying them together would
    mean tuning one silently retunes the other.
    """
    cfg = dict(pipeline_config.get("forecast", {}))
    cfg.setdefault("forward_horizon_hours", DEFAULT_FORWARD_HORIZON_HOURS)
    return cfg


def run_forecast(
    detection: Detection,
    current_path: str,
    wind_path: str,
    acquired_at: datetime.datetime,
    pipeline_config: dict,
    n_members: int | None = None,
    kernel: DriftKernel | None = None,
) -> xr.Dataset:
    """Runs the forward ensemble and bins it into a normalised forecast
    field with dims (time, lat, lon), summing to 1 over the volume.

    The returned Dataset carries `direction="forward"` in its attrs, which
    is what every consumer should check before treating a field as an
    origin field.
    """
    cfg = forecast_config(pipeline_config)
    hindcast_cfg = pipeline_config["hindcast"]
    field_cfg = hindcast_cfg["field"]

    n_members = n_members or cfg.get("n_members") or hindcast_cfg["n_members_full"]

    member_results = run_ensemble(
        detection,
        current_path,
        wind_path,
        acquired_at,
        pipeline_config,
        n_members=n_members,
        kernel=kernel,
        direction="forward",
        horizon_hours=cfg["forward_horizon_hours"],
    )

    field_ds = build_origin_field(
        member_results,
        grid_resolution_deg=field_cfg["grid_resolution_deg"],
        time_step_minutes=field_cfg["time_step_minutes"],
        gaussian_bandwidth_deg=field_cfg["gaussian_bandwidth_deg"],
        seed=pipeline_config["seed"],
        kernel=(kernel.name if kernel is not None else hindcast_cfg.get("kernel", "openoil")),
        forcing_source=cfg.get("forcing_source", "unspecified"),
        direction="forward",
    )

    # A drift kernel stops when it runs out of forcing, and it stops
    # quietly: the run simply returns fewer steps. Left unrecorded that
    # turns a config asking for 24 hours into a 6 hour forecast that
    # still gets captioned "24 hours", which is exactly the kind of
    # overclaim the rest of this pipeline is built to avoid. Both
    # numbers go into the field so the caption can read the achieved one
    # and the provenance page can show the gap.
    requested = float(cfg["forward_horizon_hours"])
    achieved = _span_hours(field_ds)
    field_ds.attrs["requested_horizon_hours"] = requested
    field_ds.attrs["achieved_horizon_hours"] = achieved
    field_ds.attrs["horizon_truncated"] = int(achieved < requested - TRUNCATION_TOLERANCE_HOURS)
    return field_ds


def _span_hours(field_ds: xr.Dataset) -> float:
    """The horizon the particles covered.

    Reads the run's own recorded span in preference to the grid's time
    coordinate: the coordinate holds bin centres and extends half a step
    past the last sample, so measuring it would report a 24 hour
    forecast as 24.5 and then flag it as not truncated by half an hour
    of slack rather than on the physics.
    """
    if "horizon_hours" in field_ds.attrs:
        return float(field_ds.attrs["horizon_hours"])
    times = field_ds["time"].values
    if len(times) < 2:
        return 0.0
    return float((times.max() - times.min()) / np.timedelta64(1, "h"))


# A forecast is binned onto the field's own time step, so the achieved
# span is allowed to fall short of the requested one by up to one bin
# without that counting as truncation.
TRUNCATION_TOLERANCE_HOURS = 1.0


def horizon_note(field_ds: xr.Dataset) -> str:
    """One line stating what the forecast actually covers, for the
    caption and the dossier. Says so plainly when the forcing ran out
    before the requested horizon did."""
    achieved = float(field_ds.attrs.get("achieved_horizon_hours", _span_hours(field_ds)))
    requested = float(field_ds.attrs.get("requested_horizon_hours", achieved))
    if not int(field_ds.attrs.get("horizon_truncated", 0)):
        return f"{achieved:.0f} hour forecast horizon."
    return (
        f"{achieved:.0f} hour forecast horizon, short of the {requested:.0f} hours requested: "
        "the forcing data ends before the horizon does."
    )


def is_forecast(field_ds) -> bool:
    """True if this field came from a forward run.

    Absent attrs read as backward. A field with no direction recorded
    predates this flag or was hand-built in a test, and in both cases it
    is a backward field; only an explicit "forward" is a forecast.
    """
    attrs = getattr(field_ds, "attrs", {}) or {}
    return str(attrs.get("direction", "backward")) == "forward"


def assert_not_scoring_input(field_ds) -> None:
    """Raises if a forecast field is about to be used where an origin
    field belongs.

    Call it at the top of anything that scores, eliminates or ranks. The
    two fields have identical shapes and dtypes, so nothing else would
    catch the substitution: the numbers would simply be wrong, and wrong
    in the direction of accusing a vessel for drift that happened after
    the evidence was recorded.
    """
    if is_forecast(field_ds):
        raise ValueError(
            "a forward forecast field was passed where the backward origin field belongs. "
            "The forecast is a response planning product and is never an input to "
            "attribution. See PLAN.md section 15."
        )


def reachable_mass_within(field_ds: xr.Dataset, hours: float) -> float:
    """Fraction of the forecast's probability mass that falls within the
    first `hours` of the run.

    The number a responder actually asks for: how much of the forecast is
    inside the window they can still act in.
    """
    times = field_ds["time"].values
    if len(times) == 0:
        return 0.0
    cutoff = times.min() + np.timedelta64(int(round(hours * 60)), "m")
    within = field_ds["probability"].sel(time=slice(None, cutoff))
    return float(within.values.sum())
