"""Guards the central claim of the project, PLAN.md section 16: "a test
that a vessel with a dark gap overlapping the field scores strictly
higher than an identical vessel without one."
"""

import copy
import datetime

import pytest
import xarray as xr

from services.core.scoring.engine import score_vessels
from services.core.schemas import AISPoint, AISTrack, DarkGap, SlickFeatures

FIELD_FIXTURE = "data/fixtures/synthetic_origin_field.nc"

SCORING_CONFIG = {
    "factors": {
        "field_integral": {"weight": 3.0},
        "dark_overlap": {"weight": 2.5},
        "axis_alignment": {"weight": 1.5},
        "speed_anomaly": {"weight": 1.0},
        "course_anomaly": {"weight": 0.75},
        "vessel_plausibility": {"weight": 0.25},
    },
}

SLICK_FEATURES = SlickFeatures(
    detection_id="d", area_km2=1.0, perimeter_km=4.0, complexity_ratio=1.2,
    major_axis_deg=45.0, elongation=3.0, mean_backscatter_db=-25.0, contrast_db=-10.0,
    age_band="fresh", age_reasoning="t",
)


def test_dark_gap_overlapping_the_field_strictly_increases_score():
    field_ds = xr.open_dataset(FIELD_FIXTURE)

    peak_lat = float(field_ds["lat"].values[len(field_ds["lat"]) // 2])
    peak_lon = float(field_ds["lon"].values[len(field_ds["lon"]) // 2])
    t_min = field_ds["time"].values.min()
    t_max = field_ds["time"].values.max()
    import pandas as pd
    t_mid = pd.Timestamp((t_min.astype("int64") + t_max.astype("int64")) // 2).to_pydatetime()

    base_points = [
        AISPoint(ts=t_mid - datetime.timedelta(hours=1), lat=peak_lat - 0.05, lon=peak_lon - 0.05, sog=8.0, cog=45.0),
        AISPoint(ts=t_mid, lat=peak_lat, lon=peak_lon, sog=8.0, cog=45.0),
        AISPoint(ts=t_mid + datetime.timedelta(hours=1), lat=peak_lat + 0.05, lon=peak_lon + 0.05, sog=8.0, cog=45.0),
    ]

    track_without_gap = AISTrack(mmsi="A", vessel_type="tanker", points=copy.deepcopy(base_points), dark_gaps=[])

    envelope = {
        "type": "Polygon",
        "coordinates": [[
            [peak_lon - 0.05, peak_lat - 0.05],
            [peak_lon - 0.05, peak_lat + 0.05],
            [peak_lon + 0.05, peak_lat + 0.05],
            [peak_lon + 0.05, peak_lat - 0.05],
            [peak_lon - 0.05, peak_lat - 0.05],
        ]],
    }
    track_with_gap = AISTrack(
        mmsi="B",
        vessel_type="tanker",
        points=copy.deepcopy(base_points),
        dark_gaps=[
            DarkGap(
                start=t_mid - datetime.timedelta(minutes=20),
                end=t_mid + datetime.timedelta(minutes=20),
                duration_min=40.0,
                entry_point=(peak_lon - 0.02, peak_lat - 0.02),
                exit_point=(peak_lon + 0.02, peak_lat + 0.02),
                envelope=envelope,
            )
        ],
    )

    scores_without = score_vessels([track_without_gap], field_ds, SLICK_FEATURES, SCORING_CONFIG)
    scores_with = score_vessels([track_with_gap], field_ds, SLICK_FEATURES, SCORING_CONFIG)

    assert scores_with[0].total > scores_without[0].total
    assert scores_with[0].factors["dark_overlap"] > scores_without[0].factors["dark_overlap"]
