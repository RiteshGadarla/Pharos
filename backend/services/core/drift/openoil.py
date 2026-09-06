"""OpenDrift OpenOil kernel, the default. See PLAN.md section 9.1.

This is the kernel that models a surface oil slick: advection by
current and wind, plus the OpenOil weathering processes. It is the one
used for the hero scenario.

The ensemble around it, not this file, is the contribution: see
hindcast/ensemble.py.
"""

from __future__ import annotations

import datetime

import numpy as np

from services.core.drift.kernel import Forcing, KernelParams


def _result_to_samples(result, seed_time: datetime.datetime) -> np.ndarray:
    """Converts an OpenDrift result Dataset, dims (trajectory, time),
    into the kernel protocol's (n_particles, n_steps, 3) array.

    Inactive particles are written as NaN rather than dropped, so the
    array stays rectangular and samples_to_arrays filters them out.
    """
    lat = result["lat"].values.astype(np.float64)  # (trajectory, time)
    lon = result["lon"].values.astype(np.float64)
    status = result["status"].values
    times = result["time"].values.astype("datetime64[s]").astype(np.float64)  # (time,)

    active = status == 0  # OpenDrift: 0 is the active/moving status
    lat = np.where(active, lat, np.nan)
    lon = np.where(active, lon, np.nan)

    n_traj, n_steps = lat.shape
    time_grid = np.broadcast_to(times[None, :], (n_traj, n_steps))
    return np.stack([lat, lon, time_grid], axis=-1)


class OpenOilKernel:
    """OpenDrift's OpenOil module, run with a negative time step for the
    backward hindcast and a positive one for the forward forecast."""

    name = "openoil"

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
        from opendrift.models.openoil import OpenOil
        from opendrift.readers import reader_netCDF_CF_generic

        o = OpenOil(loglevel=50)
        o.set_config("drift:current_uncertainty", params.current_uncertainty_ms)
        o.set_config("environment:fallback:horizontal_diffusivity", params.horizontal_diffusivity)
        o.add_reader(
            [
                reader_netCDF_CF_generic.Reader(forcing.current_path),
                reader_netCDF_CF_generic.Reader(forcing.wind_path),
            ]
        )

        seed_time = t0 + datetime.timedelta(minutes=params.seed_time_jitter_minutes)
        np.random.seed(params.member_seed)
        o.seed_elements(
            lon=seed_lon,
            lat=seed_lat,
            time=seed_time,
            wind_drift_factor=params.wind_drift_factor,
        )
        step_seconds = int(params.time_step_minutes * 60)
        o.run(
            duration=datetime.timedelta(hours=horizon_hours),
            time_step=-step_seconds if backward else step_seconds,
        )
        return _result_to_samples(o.result, seed_time)

    def run_backward(self, seed_lon, seed_lat, t0, horizon_hours, forcing, params) -> np.ndarray:
        return self._run(seed_lon, seed_lat, t0, horizon_hours, forcing, params, backward=True)

    def run_forward(self, seed_lon, seed_lat, t0, horizon_hours, forcing, params) -> np.ndarray:
        return self._run(seed_lon, seed_lat, t0, horizon_hours, forcing, params, backward=False)
