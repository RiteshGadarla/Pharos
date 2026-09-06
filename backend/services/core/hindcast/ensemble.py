"""Drift ensemble, run backward or forward. See PLAN.md sections 9 and 15.

The ensemble construction is the contribution here, not the drift model
itself: n_members independent runs, each seeded with particles
uniformly inside the slick polygon and its own perturbed forcing (wind
drift factor, current uncertainty, horizontal diffusivity, seed time
jitter), all sampled from config with a fixed seed so two runs of the
demo produce identical numbers (PLAN.md non-negotiable 7).

Which physics propagates those particles is a plug-in: the kernel comes
from `hindcast.kernel` in config/pipeline.yaml and satisfies the
DriftKernel protocol in drift/kernel.py. OpenOil for slicks, Leeway for
drifting objects, null for fixed-position events. Everything downstream
of this module consumes (n_particles, n_steps, 3) sample arrays and
never asks what produced them, which is what makes the engine event
agnostic rather than an oil pipeline with an abstraction bolted on.

Direction is a parameter of the run, not of the module. The backward run
answers "where did this come from", which is what the attribution rests
on; the forward run answers "where does it go next", which is the
response planning product in PLAN.md section 15. They share the seed
particles, the member perturbations and the field builder, so the two
halves of the drift picture meet exactly at the acquisition instant
instead of being two independently drifting stories.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import numpy as np
from shapely.geometry import Point, shape
from shapely.geometry.polygon import Polygon

from services.core.drift.kernel import DriftKernel, Forcing, KernelParams, get_kernel
from services.core.schemas import Detection

DEFAULT_KERNEL = "openoil"


@dataclass(frozen=True)
class EnsembleMemberConfig:
    member_seed: int
    wind_drift_factor: float
    current_uncertainty_ms: float
    horizontal_diffusivity: float
    seed_time_jitter_minutes: float

    def to_kernel_params(self, time_step_minutes: float) -> KernelParams:
        return KernelParams(
            member_seed=self.member_seed,
            wind_drift_factor=self.wind_drift_factor,
            current_uncertainty_ms=self.current_uncertainty_ms,
            horizontal_diffusivity=self.horizontal_diffusivity,
            seed_time_jitter_minutes=self.seed_time_jitter_minutes,
            time_step_minutes=time_step_minutes,
        )


def current_uncertainty_range(hindcast_cfg: dict) -> tuple[float, float]:
    """The range of surface current error the ensemble samples, in m/s.

    Prefers `current_perturbation_range`. Falls back to the older scalar
    `current_perturbation_magnitude`, which every member then shares.

    Sampling this per member rather than fixing it matters. It is the
    only one of the four perturbations that used to be held constant
    across the ensemble, which meant the ensemble asserted it knew the
    surface current error exactly while admitting uncertainty about wind
    drift, diffusivity and acquisition time. For a surface slick the
    current is the dominant forcing, so that was the wrong one to be
    certain about, and it left the members far too tightly clustered.
    """
    if "current_perturbation_range" in hindcast_cfg:
        lo, hi = hindcast_cfg["current_perturbation_range"]
        return float(lo), float(hi)
    magnitude = float(hindcast_cfg["current_perturbation_magnitude"])
    return magnitude, magnitude


def sample_member_configs(n_members: int, hindcast_cfg: dict, rng: np.random.Generator) -> list[EnsembleMemberConfig]:
    """Draws one perturbed parameter set per ensemble member, deterministic
    given rng's seeded state."""
    wind_lo, wind_hi = hindcast_cfg["wind_drift_factor_range"]
    diff_lo, diff_hi = hindcast_cfg["horizontal_diffusivity_range"]
    current_lo, current_hi = current_uncertainty_range(hindcast_cfg)
    jitter_minutes = hindcast_cfg["seed_time_jitter_minutes"]

    return [
        EnsembleMemberConfig(
            member_seed=int(rng.integers(0, 2**31 - 1)),
            wind_drift_factor=float(rng.uniform(wind_lo, wind_hi)),
            current_uncertainty_ms=float(rng.uniform(current_lo, current_hi)),
            horizontal_diffusivity=float(rng.uniform(diff_lo, diff_hi)),
            seed_time_jitter_minutes=float(rng.uniform(-jitter_minutes, jitter_minutes)),
        )
        for _ in range(n_members)
    ]


def seed_points_in_polygon(polygon: Polygon, n_points: int, rng: np.random.Generator) -> tuple[list[float], list[float]]:
    """Uniformly seeds n_points inside a polygon by rejection sampling
    against its bounding box."""
    minx, miny, maxx, maxy = polygon.bounds
    lons: list[float] = []
    lats: list[float] = []
    max_attempts = n_points * 500
    attempts = 0
    while len(lons) < n_points and attempts < max_attempts:
        batch = min(n_points - len(lons), 200)
        xs = rng.uniform(minx, maxx, size=batch)
        ys = rng.uniform(miny, maxy, size=batch)
        for x, y in zip(xs, ys):
            attempts += 1
            if polygon.contains(Point(x, y)):
                lons.append(float(x))
                lats.append(float(y))
            if len(lons) >= n_points:
                break
    if len(lons) < n_points:
        raise ValueError(f"could not seed {n_points} points inside the polygon after {max_attempts} attempts")
    return lons, lats


def resolve_kernel(pipeline_config: dict) -> DriftKernel:
    """Which DriftKernel this run uses, from config. See PLAN.md section 9.1."""
    hindcast_cfg = pipeline_config.get("hindcast", {})
    return get_kernel(hindcast_cfg.get("kernel", DEFAULT_KERNEL))


def run_ensemble(
    detection: Detection,
    current_path: str,
    wind_path: str,
    acquired_at: datetime.datetime,
    pipeline_config: dict,
    n_members: int | None = None,
    kernel: DriftKernel | None = None,
    direction: str = "backward",
    horizon_hours: float | None = None,
) -> list[np.ndarray]:
    """Runs the full ensemble for one detection's slick polygon.

    Returns one (n_particles, n_steps, 3) array of lat, lon and epoch
    seconds per member, in member order. Pass `kernel` to override the
    configured one; otherwise it comes from `hindcast.kernel`.

    `direction` picks which end of the kernel protocol runs.
    "backward" is the origin question and defaults to
    `hindcast.backward_horizon_hours`; "forward" is the forecast and
    needs `horizon_hours` from the caller, because a forecast horizon is
    a response planning decision and does not belong under `hindcast`.

    The seed particles and the member perturbations are drawn from the
    global seed before the direction is consulted, so a backward and a
    forward run of the same detection start from exactly the same
    particles under exactly the same sampled physics.
    """
    if direction not in ("backward", "forward"):
        raise ValueError(f"direction must be 'backward' or 'forward', got {direction!r}")

    hindcast_cfg = pipeline_config["hindcast"]
    global_seed = pipeline_config["seed"]

    n_members = n_members or hindcast_cfg["n_members_full"]
    rng = np.random.default_rng(global_seed)

    polygon = shape(detection.geometry)
    seed_lon, seed_lat = seed_points_in_polygon(polygon, hindcast_cfg["particles_per_member"], rng)
    member_configs = sample_member_configs(n_members, hindcast_cfg, rng)

    drift_kernel = kernel or resolve_kernel(pipeline_config)
    forcing = Forcing(current_path=current_path, wind_path=wind_path)
    time_step_minutes = hindcast_cfg["field"]["time_step_minutes"]

    if horizon_hours is None:
        if direction == "forward":
            raise ValueError("a forward run needs an explicit horizon_hours, see config forecast.forward_horizon_hours")
        horizon_hours = hindcast_cfg["backward_horizon_hours"]

    run = drift_kernel.run_backward if direction == "backward" else drift_kernel.run_forward

    return [
        run(
            seed_lon,
            seed_lat,
            acquired_at,
            horizon_hours,
            forcing,
            member_cfg.to_kernel_params(time_step_minutes),
        )
        for member_cfg in member_configs
    ]
