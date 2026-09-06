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
    # Which sensor produced this scene, from the SensorAdapter that read
    # it (PLAN.md section 5A). Carried through to the dossier provenance
    # page, so a claim of sensor agnosticism is demonstrated rather than
    # asserted.
    sensor: str = "S1"


class Detection(BaseModel):
    detection_id: str
    scene_id: str
    class_name: Literal["oil", "look_alike", "ship", "wake", "background"]
    geometry: dict  # GeoJSON Polygon, EPSG:4326
    mean_class_prob: float
    pixel_area: int


class ShipTarget(BaseModel):
    """A hull the SAR image itself shows, from the model's Ships class.
    See PLAN.md section 11.

    matched_mmsi is None when no AIS position sits within the match
    radius at acquisition time. That is a radar observed dark vessel:
    an independent sensor observation, not an inference from missing
    data. It is never on its own a claim of guilt, see the caveats in
    PLAN.md section 11.
    """

    target_id: str
    scene_id: str
    centroid: tuple[float, float]  # lon, lat, EPSG:4326
    pixel_area: int
    mean_backscatter_db: float
    matched_mmsi: str | None = None
    match_distance_m: float | None = None
    match_confidence: float = 0.0


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


class OpticalCorroboration(BaseModel):
    """Whether a near-coincident optical acquisition supports the SAR
    detection. See PLAN.md section 7.

    Three honest states only. no_coverage is the common one and is not a
    failure: SAR is the primary sensor precisely because it is all
    weather, day and night, and free of cloud dependence.
    """

    detection_id: str
    status: Literal["agree", "disagree", "no_coverage"]
    sensor: str | None = None
    acquired_at: datetime | None = None
    delta_hours: float | None = None
    reasoning: str


class OriginField(BaseModel):
    field_id: str
    detection_id: str
    path: str  # NetCDF, dims (time, lat, lon), normalised to sum 1
    t_min: datetime
    t_max: datetime
    n_members: int
    seed: int
    kernel: str = "openoil"  # which DriftKernel produced it, PLAN.md section 9.1
    # Which way time ran. "backward" is the origin field the attribution
    # rests on; "forward" is the response planning forecast of PLAN.md
    # section 15, which is never a scoring input. The two are the same
    # shape and dtype, so this field is the only thing that tells them
    # apart. See forecast/forward.py:assert_not_scoring_input.
    direction: Literal["backward", "forward"] = "backward"


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


class IntegrityFlag(BaseModel):
    """One AIS self-report inconsistency. See PLAN.md section 10, F7.

    This exists so that "AIS can be spoofed, not just switched off" is
    answered with a factor rather than a shrug.
    """

    kind: Literal["no_imo", "implied_speed", "static_change", "mmsi_reuse", "position_jump"]
    at: datetime
    detail: str
    severity: float = Field(ge=0.0, le=1.0)


class AISTrack(BaseModel):
    mmsi: str
    vessel_type: str
    points: list[AISPoint]
    dark_gaps: list[DarkGap] = Field(default_factory=list)
    integrity_flags: list[IntegrityFlag] = Field(default_factory=list)


class SuspectScore(BaseModel):
    mmsi: str
    total: float
    factors: dict[str, float]  # factor name -> contribution, must sum to total
    rank: int
    narrative: str  # one paragraph, generated from factors
    # The ShipTarget.target_id backing F8, when an unmatched radar
    # target fell inside this vessel's dark envelope over live field
    # mass. None means F8 did not fire, which is the ordinary case.
    radar_support: str | None = None

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


class MarpolAssessment(BaseModel):
    """Which MARPOL Annex I conditions the reconstructed behaviour
    appears not to satisfy. See PLAN.md section 13.

    Never a determination of illegality. Oil content in ppm is not
    observable from satellite, so conditions_met can never be asserted
    on that basis and the code must not attempt it.
    """

    mmsi: str
    en_route: bool | None = None
    distance_to_land_nm: float | None = None
    in_special_area: bool | None = None
    # A band (low, high), never a scalar: the thickness of a slick is
    # not observable from SAR, so the volume behind this rate is only
    # ever known to an order of magnitude.
    est_discharge_l_per_nm: tuple[float, float] | None = None
    flag: Literal["conditions_not_met", "conditions_met", "insufficient_data"]
    assumptions: list[str] = Field(default_factory=list)  # printed verbatim in the dossier

    @model_validator(mode="after")
    def discharge_is_a_band(self) -> "MarpolAssessment":
        band = self.est_discharge_l_per_nm
        if band is None:
            return self
        if len(band) != 2 or band[1] < band[0]:
            raise ValueError(
                "MarpolAssessment.est_discharge_l_per_nm must be an ordered "
                f"(low, high) band, got {band}"
            )
        return self


class CaseVerdict(BaseModel):
    """The case's outcome class. See PLAN.md section 12, "Verdict assignment".

    DARK_CONFIRMED is not a failure state. Every competing system treats
    "no broadcasting suspect" as no result; for an intelligence
    organisation it is the finding.
    """

    case_id: str
    verdict: Literal["ATTRIBUTED", "RANKED", "DARK_CONFIRMED"]
    reasoning: str = Field(min_length=1)
    top_suspects: list[str] = Field(default_factory=list)  # mmsi, ordered
    unmatched_targets: list[str] = Field(default_factory=list)  # ShipTarget ids
    infrastructure_flag: bool = False
