"""Runs a small real backward ensemble once and caches the resulting
origin probability field, so P7/P8 tests (AIS scenario generation,
scoring) don't each pay the cost of a fresh OpenDrift run.

Not a demo artifact (that's data/precomputed/, built by
scripts/seed_demo.py once later phases exist). This is a test fixture.

Run: python3 scripts/make_fixture_origin_field.py
"""

from __future__ import annotations

import datetime

from services.core.hindcast.ensemble import run_ensemble
from services.core.hindcast.field import build_origin_field
from services.core.schemas import Detection

OUT_PATH = "data/fixtures/synthetic_origin_field.nc"
CURRENTS_FIXTURE = "data/fixtures/synthetic_currents.nc"
WIND_FIXTURE = "data/fixtures/synthetic_wind_offshore.nc"
ACQUIRED_AT = datetime.datetime(2026, 1, 15, 2, 30)

DETECTION = Detection(
    detection_id="det-fixture-1",
    scene_id="SCENE-FIXTURE",
    class_name="oil",
    geometry={
        "type": "Polygon",
        "coordinates": [[[67.98, 16.98], [67.98, 17.02], [68.02, 17.02], [68.02, 16.98], [67.98, 16.98]]],
    },
    mean_class_prob=0.9,
    pixel_area=100,
)

CONFIG = {
    "seed": 26143,
    "hindcast": {
        "n_members_full": 8,
        "particles_per_member": 30,
        "backward_horizon_hours": 6,
        "wind_drift_factor_range": [0.02, 0.04],
        "current_perturbation_magnitude": 0.05,
        "horizontal_diffusivity_range": [1.0, 10.0],
        "seed_time_jitter_minutes": 15,
        "field": {"time_step_minutes": 20},
    },
}


def main() -> None:
    results = run_ensemble(DETECTION, CURRENTS_FIXTURE, WIND_FIXTURE, ACQUIRED_AT, CONFIG)
    field_ds = build_origin_field(
        results,
        grid_resolution_deg=0.01,
        time_step_minutes=CONFIG["hindcast"]["field"]["time_step_minutes"],
        gaussian_bandwidth_deg=0.02,
        seed=CONFIG["seed"],
    )
    field_ds.to_netcdf(OUT_PATH)
    print(f"wrote {OUT_PATH}, dims={dict(field_ds.sizes)}, sum={float(field_ds['probability'].values.sum()):.6f}")


if __name__ == "__main__":
    main()
