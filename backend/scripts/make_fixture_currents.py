"""Generates the synthetic, CF-compliant ocean current and sea surface
temperature NetCDF, readable directly by OpenDrift's
reader_netCDF_CF_generic.

Not real CMEMS or HYCOM data, and not a reanalysis of any kind. Stands
in until Copernicus Marine access is wired up (PLAN.md section 4A).

The domain is open Arabian Sea, well clear of the real coastline: a 48 h
backward drift near-shore can strand every ensemble member on real land
(GSHHG is real coastline data even for a synthetic scenario), which says
nothing useful about the ensemble mechanism itself. The forcing covers 60
hours before acquisition, for the 48 hour backward horizon plus margin,
and 30 after, for the 24 hour forward forecast plus margin; a shorter
fixture quietly clips the forecast.

The field comes from scripts/synthetic_metocean.py, which documents each
component: the seasonal background flow, westward drifting mesoscale
eddies with cold and warm cores in SST, a weak submesoscale field, the
M2 tide, and a near-inertial oscillation at the local Coriolis period
(about 41 h at 17 N). It used to be one rotational gyre, breathing on a
sine wave, with a tide added uniformly. The parameters for this file are
the default case's in config/cases.yaml; other cases are written beside
it by make_fixture_cases.py.

Run: python3 scripts/make_fixture_currents.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import case_registry  # noqa: E402
import synthetic_metocean  # noqa: E402

OUT_PATH = case_registry.DEFAULT_CURRENTS


def build_case(case: dict, out_path: str) -> None:
    forcing = case.get("forcing", {})
    ds = synthetic_metocean.make_currents_dataset(
        forcing.get("currents"),
        case_registry.acquired_at(case),
        seed=case_registry.seeds(case)["currents"],
        domain=forcing.get("domain"),
    )
    ds.to_netcdf(out_path)
    print(
        f"wrote {out_path}, dims={dict(ds.sizes)}, current mean {ds.attrs['speed_mean_ms']} m/s, "
        f"max {ds.attrs['speed_max_ms']} m/s"
    )


if __name__ == "__main__":
    registry = case_registry.load_registry()
    build_case(case_registry.get_case(registry, registry["default_case"]), OUT_PATH)
