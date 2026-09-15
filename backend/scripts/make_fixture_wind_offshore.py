"""Generates the synthetic 10 m wind and 2 m air temperature NetCDF for
the backward drift ensemble and the console, covering the same
open-ocean domain and time range as make_fixture_currents.py.

Not real ERA5 or GFS data, and not a reanalysis of any kind. Stands in
until CDS or the no-auth GFS S3 fallback is wired up (PLAN.md section
4A). A separate fixture from synthetic_wind.nc, the wind gate's unit
fixture, which is scoped around a near-shore test box and deliberately
has four distinct wind zones.

The field itself comes from scripts/synthetic_metocean.py, which
documents each physical component (synoptic flow with veer and trend, a
spatially correlated mesoscale field, the land-sea breeze, red-noise
gustiness, a Weibull speed distribution). It used to be a steady
background plus a linear gradient, a slow veer and a sine wave, which
drew as a field of near-identical arrows rotating in lockstep: weather
as a formula. The parameters for this file are the default case's in
config/cases.yaml, so the fixture the tests read and the hero case's
forcing are the same data. Every other case's wind is written beside it
by make_fixture_cases.py from the same generator.

Run: python3 scripts/make_fixture_wind_offshore.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import case_registry  # noqa: E402
import synthetic_metocean  # noqa: E402

OUT_PATH = case_registry.DEFAULT_WIND


def build_case(case: dict, out_path: str) -> None:
    forcing = case.get("forcing", {})
    ds = synthetic_metocean.make_wind_dataset(
        forcing.get("wind"),
        case_registry.acquired_at(case),
        seed=case_registry.seeds(case)["wind"],
        domain=forcing.get("domain"),
    )
    ds.to_netcdf(out_path)
    print(
        f"wrote {out_path}, dims={dict(ds.sizes)}, pass wind {ds.attrs['pass_speed_ms']} m/s, "
        f"mean {ds.attrs['speed_mean_ms']} m/s, skewness {ds.attrs['speed_skewness']}"
    )


if __name__ == "__main__":
    registry = case_registry.load_registry()
    build_case(case_registry.get_case(registry, registry["default_case"]), OUT_PATH)
