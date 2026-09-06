"""OpenDrift OceanDrift kernel, for drifting objects and debris.
See PLAN.md section 9.1.

Same ensemble, same field construction, same AIS scoring, same
elimination log, same verdict, same dossier. The only thing that
changes is what physics moved the thing. Selecting this kernel in
config/pipeline.yaml is the one-line diff that turns an oil spill
attribution engine into a general maritime event attribution engine
(PLAN.md phase P14).

OceanDrift rather than the Leeway model itself: Leeway needs an object
category from the search and rescue taxonomy, which a generic drifting
object does not have. OceanDrift with a configurable wind drift factor
is the honest general case, and the wind drift factor is exactly the
parameter the ensemble already perturbs.
"""

from __future__ import annotations

import datetime

import numpy as np

from services.core.drift.kernel import Forcing, KernelParams
from services.core.drift.openoil import _result_to_samples


class LeewayKernel:
    """A passively drifting object under current plus a wind drift
    factor. No weathering, no oil chemistry."""

    name = "leeway"

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
        from opendrift.models.oceandrift import OceanDrift
        from opendrift.readers import reader_netCDF_CF_generic

        o = OceanDrift(loglevel=50)
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
