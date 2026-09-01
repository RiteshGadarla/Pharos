"""Backward drift ensemble via OpenDrift's OpenOil backend. See PLAN.md
section 8.

The ensemble construction is the contribution here, not the drift model
itself: n_members independent backward runs, each seeded with particles
uniformly inside the slick polygon and its own perturbed forcing (wind
drift factor, current uncertainty, horizontal diffusivity, seed time
jitter), all sampled from config with a fixed seed so two runs of the
demo produce identical numbers (PLAN.md non-negotiable 6).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import numpy as np
import xarray as xr
from opendrift.models.openoil import OpenOil
from opendrift.readers import reader_netCDF_CF_generic
from shapely.geometry import Point, shape
from shapely.geometry.polygon import Polygon

from services.core.schemas import Detection


@dataclass(frozen=True)
class EnsembleMemberConfig:
    member_seed: int
    wind_drift_factor: float
    current_uncertainty_ms: float
    horizontal_diffusivity: float
    seed_time_jitter_minutes: float


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


def run_member(
    member_cfg: EnsembleMemberConfig,
    seed_lon: list[float],
    seed_lat: list[float],
    acquired_at: datetime.datetime,
    current_reader,
    wind_reader,
    backward_horizon_hours: float,
    time_step_minutes: float,
) -> xr.Dataset:
    """Runs one backward ensemble member. Returns OpenDrift's own result
    Dataset, dims (trajectory, time)."""
    o = OpenOil(loglevel=50)
    o.set_config("drift:current_uncertainty", member_cfg.current_uncertainty_ms)
    o.set_config("environment:fallback:horizontal_diffusivity", member_cfg.horizontal_diffusivity)
    o.add_reader([current_reader, wind_reader])

    seed_time = acquired_at + datetime.timedelta(minutes=member_cfg.seed_time_jitter_minutes)
    np.random.seed(member_cfg.member_seed)
    o.seed_elements(
        lon=seed_lon,
        lat=seed_lat,
        time=seed_time,
        wind_drift_factor=member_cfg.wind_drift_factor,
    )
    o.run(
        duration=datetime.timedelta(hours=backward_horizon_hours),
        time_step=-int(time_step_minutes * 60),
    )
    return o.result


def run_ensemble(
    detection: Detection,
    current_path: str,
    wind_path: str,
    acquired_at: datetime.datetime,
    pipeline_config: dict,
    n_members: int | None = None,
) -> list[xr.Dataset]:
    """Runs the full backward ensemble for one detection's slick polygon.
    Returns one OpenDrift result Dataset per member, in member order."""
    hindcast_cfg = pipeline_config["hindcast"]
    global_seed = pipeline_config["seed"]

    n_members = n_members or hindcast_cfg["n_members_full"]
    rng = np.random.default_rng(global_seed)

    polygon = shape(detection.geometry)
    seed_lon, seed_lat = seed_points_in_polygon(polygon, hindcast_cfg["particles_per_member"], rng)
    member_configs = sample_member_configs(n_members, hindcast_cfg, rng)

    current_reader = reader_netCDF_CF_generic.Reader(current_path)
    wind_reader = reader_netCDF_CF_generic.Reader(wind_path)

    return [
        run_member(
            member_cfg,
            seed_lon,
            seed_lat,
            acquired_at,
            current_reader,
            wind_reader,
            hindcast_cfg["backward_horizon_hours"],
            hindcast_cfg["field"]["time_step_minutes"],
        )
        for member_cfg in member_configs
    ]
