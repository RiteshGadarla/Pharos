"""Data contracts shared by every pipeline stage. See PLAN.md section 4.

Stages communicate through the database and object paths, never through
in-memory coupling: everything that crosses a stage boundary is one of
these models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

FACTOR_SUM_TOLERANCE = 1e-6


class SceneMeta(BaseModel):
    scene_id: str
    acquired_at: datetime
    bbox: tuple[float, float, float, float]  # minlon, minlat, maxlon, maxlat
    crs: str
    source_path: str


class Detection(BaseModel):
    detection_id: str
    scene_id: str
    class_name: Literal["oil", "look_alike", "ship", "wake", "background"]
    geometry: dict  # GeoJSON Polygon, EPSG:4326
    mean_class_prob: float
    pixel_area: int


class SlickFeatures(BaseModel):
    detection_id: str
    area_km2: float
    perimeter_km: float
    complexity_ratio: float  # P / (2 * sqrt(pi * A)), 1.0 is a circle
    major_axis_deg: float  # 0-180, from minimum rotated rectangle
    elongation: float  # major / minor
    mean_backscatter_db: float
    contrast_db: float  # slick mean minus local sea mean
    age_band: Literal["fresh", "intermediate", "weathered"]
    age_reasoning: str  # human readable, goes in the dossier


class GateResult(BaseModel):
    detection_id: str
    wind_speed_ms: float
    verdict: Literal["accept", "downgrade", "suppress"]
    reason: str


class OriginField(BaseModel):
    field_id: str
    detection_id: str
    path: str  # NetCDF, dims (time, lat, lon), normalised to sum 1
    t_min: datetime
    t_max: datetime
    n_members: int
    seed: int


class AISPoint(BaseModel):
    ts: datetime
    lat: float
    lon: float
    sog: float  # speed over ground, knots
    cog: float  # course over ground, degrees
    heading: float | None = None


class DarkGap(BaseModel):
    start: datetime
    end: datetime
    duration_min: float
    entry_point: tuple[float, float]
    exit_point: tuple[float, float]
    envelope: dict  # GeoJSON Polygon, dead-reckoned reachable set


class AISTrack(BaseModel):
    mmsi: str
    vessel_type: str
    points: list[AISPoint]
    dark_gaps: list[DarkGap] = Field(default_factory=list)


class SuspectScore(BaseModel):
    mmsi: str
    total: float
    factors: dict[str, float]  # factor name -> contribution, must sum to total
    rank: int
    narrative: str  # one paragraph, generated from factors

    @model_validator(mode="after")
    def factors_sum_to_total(self) -> "SuspectScore":
        factor_sum = sum(self.factors.values())
        if abs(factor_sum - self.total) > FACTOR_SUM_TOLERANCE:
            raise ValueError(
                f"SuspectScore.factors sums to {factor_sum}, "
                f"which does not match total {self.total} "
                f"within tolerance {FACTOR_SUM_TOLERANCE}"
            )
        return self


class Elimination(BaseModel):
    mmsi: str
    reason: str = Field(min_length=1)  # required, never empty
    rule: str  # machine readable rule id
