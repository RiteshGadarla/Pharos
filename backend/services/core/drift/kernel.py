"""The DriftKernel protocol. See PLAN.md section 9.1.

This is the architectural claim of the whole project made concrete: an
oil slick is instance one of a general problem shape, which is "given an
observed effect at a known place and time, reconstruct the origin window
and rank who was present in it". Everything downstream of the kernel,
the field construction, the AIS scoring, the elimination log, the
verdict, the dossier, consumes particle samples and never asks what
physics produced them.

A kernel returns a plain (n_particles, n_steps, 3) array of lat, lon and
time. That signature is deliberately narrow: swapping OpenOil for Leeway
or for the null kernel is a one-line change in config/pipeline.yaml, and
nothing downstream changes at all.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class Forcing:
    """Paths to the cached forcing fields a kernel reads.

    Both are local NetCDF files. Nothing here touches the network at
    run time, per non-negotiable 6.
    """

    current_path: str
    wind_path: str


@dataclass(frozen=True)
class KernelParams:
    """One ensemble member's perturbed parameter set.

    Not every kernel uses every field. The null kernel uses none of
    them, which is the point: it still runs, and every downstream stage
    still works on its output.
    """

    member_seed: int
    wind_drift_factor: float
    current_uncertainty_ms: float
    horizontal_diffusivity: float
    seed_time_jitter_minutes: float
    time_step_minutes: float


@runtime_checkable
class DriftKernel(Protocol):
    """Anything that can propagate seeded particles through time.

    Implementations live beside this file: openoil.py (slicks, the
    default), leeway.py (drifting objects and debris), null.py (fixed
    position events).
    """

    name: str

    def run_backward(
        self,
        seed_lon: list[float],
        seed_lat: list[float],
        t0: datetime.datetime,
        horizon_hours: float,
        forcing: Forcing,
        params: KernelParams,
    ) -> np.ndarray:
        """Returns (n_particles, n_steps, 3) of lat, lon, time-as-epoch-seconds."""
        ...

    def run_forward(
        self,
        seed_lon: list[float],
        seed_lat: list[float],
        t0: datetime.datetime,
        horizon_hours: float,
        forcing: Forcing,
        params: KernelParams,
    ) -> np.ndarray:
        ...


def get_kernel(name: str) -> DriftKernel:
    """Resolves the kernel named in config/pipeline.yaml.

    Imports lazily so that the null kernel, and therefore the schema and
    scoring tests, work in an environment without OpenDrift installed.
    """
    key = name.strip().lower()
    if key in {"openoil", "opendrift_openoil"}:
        from services.core.drift.openoil import OpenOilKernel

        return OpenOilKernel()
    if key in {"leeway", "oceandrift", "opendrift_leeway"}:
        from services.core.drift.leeway import LeewayKernel

        return LeewayKernel()
    if key in {"null", "fixed"}:
        from services.core.drift.null import NullKernel

        return NullKernel()
    raise ValueError(
        f"unknown drift kernel {name!r}. Known kernels: openoil, leeway, null. "
        "See PLAN.md section 9.1."
    )


def samples_to_arrays(samples: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Flattens a kernel's (n_particles, n_steps, 3) output into the
    parallel (lat, lon, time) arrays hindcast/field.py bins.

    Rows carrying a NaN position are dropped: that is how a kernel
    reports a particle that has stranded or otherwise stopped being a
    sample of where the slick could have been.
    """
    if samples.ndim != 3 or samples.shape[2] != 3:
        raise ValueError(f"kernel output must be (n_particles, n_steps, 3), got {samples.shape}")
    flat = samples.reshape(-1, 3)
    finite = np.isfinite(flat).all(axis=1)
    flat = flat[finite]
    lats = flat[:, 0]
    lons = flat[:, 1]
    times = flat[:, 2].astype("datetime64[s]")
    return lats, lons, times
