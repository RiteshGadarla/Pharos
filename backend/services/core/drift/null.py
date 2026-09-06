"""The null drift kernel: nothing moves. See PLAN.md section 9.1.

Ten lines of physics and it is the most important kernel in the
repository, because it is what proves the architecture is genuinely
general rather than an oil pipeline with an abstraction bolted on.

Use it for an event whose source does not drift: a fixed discharge
point, a platform, an acoustic or radio event with a known position.
The particles hold their seeded positions at every timestep, the field
builder still produces a normalised P(lat, lon, t) with a real time
dimension, and every downstream stage, the AIS reconstruction, the
elimination log, the scoring engine, the verdict and the dossier, runs
completely unchanged. A test asserts exactly that.

It also takes no forcing data at all, which makes it the kernel to
reach for when a stage needs a field and the environment has no
OpenDrift installed.
"""

from __future__ import annotations

import datetime

import numpy as np

from services.core.drift.kernel import Forcing, KernelParams


class NullKernel:
    """Holds every seeded particle at its seed position for the whole
    horizon. Diffusivity, wind drift and current uncertainty are
    accepted and ignored, deliberately: a fixed source does not drift,
    and pretending otherwise would put uncertainty into the field that
    the physics does not support."""

    name = "null"

    def _run(
        self,
        seed_lon: list[float],
        seed_lat: list[float],
        t0: datetime.datetime,
        horizon_hours: float,
        forcing: Forcing,
        params: KernelParams,
        backward: bool,
    ) -> np.ndarray:
        step = datetime.timedelta(minutes=params.time_step_minutes)
        n_steps = max(2, int(round(horizon_hours * 60.0 / params.time_step_minutes)) + 1)
        sign = -1 if backward else 1
        t_start = t0 + datetime.timedelta(minutes=params.seed_time_jitter_minutes)

        times = np.array(
            [(t_start + sign * i * step).timestamp() for i in range(n_steps)],
            dtype=np.float64,
        )
        lat = np.asarray(seed_lat, dtype=np.float64)[:, None].repeat(n_steps, axis=1)
        lon = np.asarray(seed_lon, dtype=np.float64)[:, None].repeat(n_steps, axis=1)
        time_grid = np.broadcast_to(times[None, :], lat.shape)
        return np.stack([lat, lon, time_grid], axis=-1)

    def run_backward(self, seed_lon, seed_lat, t0, horizon_hours, forcing, params) -> np.ndarray:
        return self._run(seed_lon, seed_lat, t0, horizon_hours, forcing, params, backward=True)

    def run_forward(self, seed_lon, seed_lat, t0, horizon_hours, forcing, params) -> np.ndarray:
        return self._run(seed_lon, seed_lat, t0, horizon_hours, forcing, params, backward=False)
