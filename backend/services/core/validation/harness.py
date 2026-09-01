"""Validation harness for the scoring engine. See PLAN.md section 13.

There is no ground truth for real-world spill attribution, so this
harness builds its own: generate synthetic incidents with a *known*
injected culprit, run the real elimination and scoring pipeline on
each, and measure how often the real culprit comes out on top. That
measures internal consistency of the scoring model, not real-world
accuracy, and the report says so explicitly. Validation against a
documented, prosecuted incident is the next step, not this.

Each incident varies three axes PLAN.md section 13 asks for directly:
traffic density (how many ordinary decoy vessels share the scene),
dark gap presence (whether the culprit ever goes dark at all), and
backward horizon / wind conditions (which of a handful of real,
independently-run backward ensembles the incident uses). Re-running
OpenDrift 50 times would be far too slow for a harness meant to be run
before a demo, so a small number of real ensembles are run once
(build_field_variants) and reused across many AIS scenarios layered on
top of them, the same way scripts/make_fixture_origin_field.py caches
one for the test suite.

Two ablations, run on every incident for a direct comparison:
  - F2 (dark_overlap) zeroed out, via a scoring_config with that
    factor's weight set to 0. Uses the real scoring engine unmodified.
  - F1 (field_integral) replaced with closeness to the field's
    time-collapsed centroid: the exact "distance to a single point"
    baseline PLAN.md non-negotiable 1 says a real system must never
    use, kept here only to measure how much worse it does.
"""

from __future__ import annotations

import copy
import datetime
import math
from dataclasses import dataclass, field

import numpy as np
import xarray as xr

from services.core.ais.synthetic import build_track, field_peak, field_time_bounds, generate_decoy_vessels, generate_demo_scenario
from services.core.hindcast.ensemble import run_ensemble
from services.core.hindcast.field import build_origin_field
from services.core.schemas import AISTrack, Detection, SlickFeatures, SuspectScore
from services.core.scoring.eliminate import eliminate_and_survive
from services.core.scoring.engine import LOGIT_EPS, build_narrative, score_vessels
from services.core.scoring.factors import compute_all_factors

CURRENTS_PATH = "data/fixtures/synthetic_currents.nc"
WIND_PATH = "data/fixtures/synthetic_wind_offshore.nc"
ACQUIRED_AT = datetime.datetime(2026, 1, 15, 2, 30)
CULPRIT_MMSI = "419000001"

# Same offshore, real-coastline-free footprint as
# scripts/make_fixture_origin_field.py, reused here so every field
# variant seeds inside the fixture forcing data's own coverage.
BASE_DETECTION = Detection(
    detection_id="det-validation-1",
    scene_id="SCENE-VALIDATION",
    class_name="oil",
    geometry={
        "type": "Polygon",
        "coordinates": [[[67.98, 16.98], [67.98, 17.02], [68.02, 17.02], [68.02, 16.98], [67.98, 16.98]]],
    },
    mean_class_prob=0.9,
    pixel_area=100,
)

SLICK_FEATURES = SlickFeatures(
    detection_id="det-validation-1", area_km2=1.0, perimeter_km=4.0, complexity_ratio=1.2,
    major_axis_deg=45.0, elongation=3.0, mean_backscatter_db=-25.0, contrast_db=-10.0,
    age_band="fresh", age_reasoning="validation harness, not a real scene",
)

# A handful of distinct, real ensemble runs standing in for the
# "backward horizon and wind conditions" axis. Each is genuinely run
# through OpenDrift/OpenOil, just fewer members than a full demo (30)
# to keep the harness fast; n_members and horizon are both smaller than
# PLAN.md's production defaults for the same reason.
FIELD_VARIANTS = {
    "short_horizon": {
        "n_members_full": 6, "particles_per_member": 25, "backward_horizon_hours": 4,
        "wind_drift_factor_range": [0.02, 0.04], "current_perturbation_magnitude": 0.03,
        "horizontal_diffusivity_range": [1.0, 8.0], "seed_time_jitter_minutes": 10,
        "field": {"grid_resolution_deg": 0.01, "time_step_minutes": 15, "gaussian_bandwidth_deg": 0.02},
    },
    "medium_horizon": {
        "n_members_full": 6, "particles_per_member": 25, "backward_horizon_hours": 6,
        "wind_drift_factor_range": [0.02, 0.04], "current_perturbation_magnitude": 0.05,
        "horizontal_diffusivity_range": [1.0, 10.0], "seed_time_jitter_minutes": 15,
        "field": {"grid_resolution_deg": 0.01, "time_step_minutes": 20, "gaussian_bandwidth_deg": 0.02},
    },
    "long_horizon_rough": {
        "n_members_full": 6, "particles_per_member": 25, "backward_horizon_hours": 9,
        "wind_drift_factor_range": [0.025, 0.045], "current_perturbation_magnitude": 0.09,
        "horizontal_diffusivity_range": [2.0, 14.0], "seed_time_jitter_minutes": 20,
        "field": {"grid_resolution_deg": 0.01, "time_step_minutes": 25, "gaussian_bandwidth_deg": 0.03},
    },
}

TRAFFIC_DENSITY_LEVELS = {"low": 0, "medium": 4, "high": 10}

NEAR_MISS_MMSI = "419000005"


def build_near_miss_vessel(field_ds: xr.Dataset, ais_config: dict, seed: int) -> AISTrack:
    """A vessel purpose-built to expose the gap between the real F1
    (time-weighted field integral) and the naive "distance to centroid"
    baseline the F1 ablation compares against: it passes directly
    through the field's own peak, but hours *before* the field's time
    window opens, then trails into the window's tail at the grid's low
    probability edge, just enough to survive elimination (a few pings
    inside the window, over a cell with non-negligible but small mass).

    A time-weighted integral correctly scores this low: almost all of
    its overlap with real mass falls outside the window entirely, and
    what little falls inside is over near-zero probability. A metric
    that measures closest approach to the centroid over the vessel's
    whole track, blind to when that approach happened, cannot tell this
    apart from the real culprit's approach, which is the exact failure
    PLAN.md non-negotiable 1 argues a single-point collapse invites."""
    rng = np.random.default_rng(seed)
    dark_gap_min = ais_config["dark_gap_min_minutes"]
    max_speed_kn = ais_config["max_plausible_speed_kn"]

    peak_lat, peak_lon, _ = field_peak(field_ds)
    t_min, t_max = field_time_bounds(field_ds)

    lat_span = float(field_ds["lat"].values.max() - field_ds["lat"].values.min())
    lon_span = float(field_ds["lon"].values.max() - field_ds["lon"].values.min())
    edge_lat = peak_lat + lat_span * 0.42
    edge_lon = peak_lon - lon_span * 0.42

    close_pass_time = t_min - datetime.timedelta(hours=3)
    waypoints = [
        (peak_lat - 0.3, peak_lon - 0.3, close_pass_time - datetime.timedelta(hours=1)),
        (peak_lat, peak_lon, close_pass_time),
        (edge_lat, edge_lon, t_max),
    ]
    return build_track(
        NEAR_MISS_MMSI, "cargo", waypoints, ping_interval_min=8, rng=rng,
        dark_gap_min_minutes=dark_gap_min, max_speed_kn=max_speed_kn,
    )


def build_field_variants(base_seed: int) -> dict[str, xr.Dataset]:
    """Runs one real backward ensemble per entry in FIELD_VARIANTS and
    returns the resulting origin fields, keyed by variant name."""
    fields: dict[str, xr.Dataset] = {}
    for name, hindcast_cfg in FIELD_VARIANTS.items():
        config = {"seed": base_seed, "hindcast": hindcast_cfg}
        member_results = run_ensemble(
            BASE_DETECTION, CURRENTS_PATH, WIND_PATH, ACQUIRED_AT, config,
            n_members=hindcast_cfg["n_members_full"],
        )
        fields[name] = build_origin_field(
            member_results,
            grid_resolution_deg=hindcast_cfg["field"]["grid_resolution_deg"],
            time_step_minutes=hindcast_cfg["field"]["time_step_minutes"],
            gaussian_bandwidth_deg=hindcast_cfg["field"]["gaussian_bandwidth_deg"],
            seed=base_seed,
        )
    return fields


@dataclass
class IncidentSpec:
    incident_id: int
    field_variant: str
    traffic_density: str
    include_dark_gap: bool
    seed: int


@dataclass
class IncidentResult:
    spec: IncidentSpec
    n_candidates: int
    culprit_eliminated: bool
    baseline_rank: int | None
    no_dark_overlap_rank: int | None
    centroid_baseline_rank: int | None
    # culprit's total score minus the best surviving competitor's, per
    # scoring variant. Rank alone only moves when a competitor's score
    # actually crosses the culprit's, which a strong culprit signal can
    # make rare; margin shows how much each ablation erodes the gap even
    # when it isn't (yet) large enough to flip the rank.
    baseline_margin: float | None = None
    no_dark_overlap_margin: float | None = None
    centroid_baseline_margin: float | None = None
    # the deliberately deceptive near-miss vessel's own total score,
    # baseline vs centroid ablation: the most direct read on whether the
    # centroid baseline actually falls for a right-place-wrong-time
    # vessel the way the real integral (correctly) does not.
    near_miss_survived: bool = False
    near_miss_baseline_total: float | None = None
    near_miss_centroid_total: float | None = None


def build_incident_specs(n_incidents: int, base_seed: int) -> list[IncidentSpec]:
    """Stratifies n_incidents across every (field_variant, traffic_density,
    dark_gap_presence) combination, cycling through the combinations and
    varying the AIS seed each time so incidents in the same cell are
    still distinct scenarios, not repeats."""
    combos = [
        (variant, density, dark_gap)
        for variant in FIELD_VARIANTS
        for density in TRAFFIC_DENSITY_LEVELS
        for dark_gap in (True, False)
    ]
    specs = []
    for i in range(n_incidents):
        variant, density, dark_gap = combos[i % len(combos)]
        specs.append(
            IncidentSpec(
                incident_id=i,
                field_variant=variant,
                traffic_density=density,
                include_dark_gap=dark_gap,
                seed=base_seed + i,
            )
        )
    return specs


def _field_centroid(field_ds: xr.Dataset) -> tuple[float, float]:
    """Mass-weighted (lat, lon) centroid, collapsed over time. This is
    exactly the collapse PLAN.md non-negotiable 1 forbids before
    scoring; it exists only as the naive baseline the F1 ablation
    measures against, never used outside this harness."""
    prob = field_ds["probability"].sum(dim="time").values
    lat = field_ds["lat"].values
    lon = field_ds["lon"].values
    total = float(prob.sum())
    lat_c = float((prob.sum(axis=1) * lat).sum() / total)
    lon_c = float((prob.sum(axis=0) * lon).sum() / total)
    return lat_c, lon_c


def _min_distance_to_point_km(track: AISTrack, point: tuple[float, float]) -> float:
    """Closest approach of the vessel's own reported track to point, over
    its *entire* lifetime, deliberately not restricted to the field's
    time window. That is the point of this ablation: a naive
    "which vessel passed closest to here" baseline is blind to time
    altogether, not just imprecise about it, which is exactly what lets
    a right-place-wrong-time vessel score as well as the real culprit."""
    from services.core.ais.tracks import haversine_km

    if not track.points:
        return float("inf")
    return min(haversine_km(p.lat, p.lon, point[0], point[1]) for p in track.points)


def _logit(p: float) -> float:
    p = min(max(p, LOGIT_EPS), 1.0 - LOGIT_EPS)
    return math.log(p / (1.0 - p))


def score_with_centroid_baseline(
    tracks: list[AISTrack], field_ds: xr.Dataset, slick_features: SlickFeatures, scoring_config: dict
) -> list[SuspectScore]:
    """Ablation baseline: identical combination to scoring/engine.py's
    score_vessels, except F1 (field_integral) is replaced by closeness
    to the field's time-collapsed centroid instead of the real
    space-time integral. Mirrors score_vessels' combination formula
    rather than importing its private helpers, since this is
    deliberately a different (and deliberately worse) scoring path, not
    a variant of the production one."""
    factor_weights = {key: cfg["weight"] for key, cfg in scoring_config["factors"].items()}
    plausibility_table = scoring_config.get("vessel_plausibility_table")
    linear_factors = {"field_integral", "dark_overlap"}

    centroid = _field_centroid(field_ds)
    raw_distance = {t.mmsi: _min_distance_to_point_km(t, centroid) for t in tracks}
    finite = [d for d in raw_distance.values() if math.isfinite(d)]
    max_d = max(finite) if finite else 1.0

    scores = []
    for track in tracks:
        raw = compute_all_factors(track, field_ds, slick_features, plausibility_table)
        dist = raw_distance[track.mmsi]
        raw["field_integral"] = 0.0 if not math.isfinite(dist) or max_d <= 0 else max(0.0, 1.0 - dist / max_d)

        contributions = {}
        for name, value in raw.items():
            weight = factor_weights[name]
            if name in linear_factors:
                contributions[name] = weight * min(max(value, 0.0), 1.0)
            else:
                contributions[name] = weight * _logit(value)
        total = sum(contributions.values())
        scores.append(SuspectScore(mmsi=track.mmsi, total=total, factors=contributions, rank=0, narrative=""))

    scores.sort(key=lambda s: s.total, reverse=True)
    return [s.model_copy(update={"rank": i, "narrative": build_narrative(s.factors, i)}) for i, s in enumerate(scores, start=1)]


def _culprit_rank(scores: list[SuspectScore], culprit_mmsi: str) -> int | None:
    for s in scores:
        if s.mmsi == culprit_mmsi:
            return s.rank
    return None


def _culprit_margin(scores: list[SuspectScore], culprit_mmsi: str) -> float | None:
    """Culprit's total minus the best-scoring competitor's. Positive
    means the culprit is ranked first and by how much; negative means
    something else outranked it."""
    culprit_total = next((s.total for s in scores if s.mmsi == culprit_mmsi), None)
    if culprit_total is None:
        return None
    others = [s.total for s in scores if s.mmsi != culprit_mmsi]
    if not others:
        return 0.0
    return culprit_total - max(others)


def run_incident(spec: IncidentSpec, field_ds: xr.Dataset, ais_config: dict, scoring_config: dict) -> IncidentResult:
    n_decoys = TRAFFIC_DENSITY_LEVELS[spec.traffic_density]
    core_tracks = generate_demo_scenario(field_ds, ais_config, spec.seed, include_culprit_dark_gap=spec.include_dark_gap)
    near_miss = build_near_miss_vessel(field_ds, ais_config, spec.seed + 200000)
    decoys = generate_decoy_vessels(field_ds, ais_config, spec.seed + 100000, n_decoys)
    tracks = core_tracks + [near_miss] + decoys

    survivors, eliminations = eliminate_and_survive(tracks, field_ds, scoring_config)
    culprit_eliminated = any(e.mmsi == CULPRIT_MMSI for e in eliminations)

    baseline_rank = no_dark_overlap_rank = centroid_rank = None
    baseline_margin = no_dark_overlap_margin = centroid_margin = None
    near_miss_survived = any(t.mmsi == NEAR_MISS_MMSI for t in survivors)
    near_miss_baseline_total = near_miss_centroid_total = None
    if not culprit_eliminated:
        baseline_scores = score_vessels(survivors, field_ds, SLICK_FEATURES, scoring_config)
        baseline_rank = _culprit_rank(baseline_scores, CULPRIT_MMSI)
        baseline_margin = _culprit_margin(baseline_scores, CULPRIT_MMSI)

        no_dark_overlap_config = copy.deepcopy(scoring_config)
        no_dark_overlap_config["factors"]["dark_overlap"]["weight"] = 0.0
        no_dark_overlap_scores = score_vessels(survivors, field_ds, SLICK_FEATURES, no_dark_overlap_config)
        no_dark_overlap_rank = _culprit_rank(no_dark_overlap_scores, CULPRIT_MMSI)
        no_dark_overlap_margin = _culprit_margin(no_dark_overlap_scores, CULPRIT_MMSI)

        centroid_scores = score_with_centroid_baseline(survivors, field_ds, SLICK_FEATURES, scoring_config)
        centroid_rank = _culprit_rank(centroid_scores, CULPRIT_MMSI)
        centroid_margin = _culprit_margin(centroid_scores, CULPRIT_MMSI)

        if near_miss_survived:
            near_miss_baseline_total = next((s.total for s in baseline_scores if s.mmsi == NEAR_MISS_MMSI), None)
            near_miss_centroid_total = next((s.total for s in centroid_scores if s.mmsi == NEAR_MISS_MMSI), None)

    return IncidentResult(
        spec=spec,
        n_candidates=len(survivors),
        culprit_eliminated=culprit_eliminated,
        baseline_rank=baseline_rank,
        no_dark_overlap_rank=no_dark_overlap_rank,
        centroid_baseline_rank=centroid_rank,
        baseline_margin=baseline_margin,
        no_dark_overlap_margin=no_dark_overlap_margin,
        centroid_baseline_margin=centroid_margin,
        near_miss_survived=near_miss_survived,
        near_miss_baseline_total=near_miss_baseline_total,
        near_miss_centroid_total=near_miss_centroid_total,
    )


@dataclass
class Accuracy:
    n: int = 0
    rank1: int = 0
    rank3: int = 0
    eliminated: int = 0
    ranks: list[int] = field(default_factory=list)
    margins: list[float] = field(default_factory=list)

    def add(self, rank: int | None, eliminated: bool, margin: float | None = None) -> None:
        self.n += 1
        if eliminated:
            self.eliminated += 1
            return
        if rank is not None:
            self.ranks.append(rank)
            if rank == 1:
                self.rank1 += 1
            if rank <= 3:
                self.rank3 += 1
        if margin is not None:
            self.margins.append(margin)

    @property
    def rank1_accuracy(self) -> float:
        return self.rank1 / self.n if self.n else 0.0

    @property
    def rank3_accuracy(self) -> float:
        return self.rank3 / self.n if self.n else 0.0

    @property
    def mean_rank(self) -> float | None:
        return sum(self.ranks) / len(self.ranks) if self.ranks else None

    @property
    def mean_margin(self) -> float | None:
        return sum(self.margins) / len(self.margins) if self.margins else None

    @property
    def elimination_rate(self) -> float:
        return self.eliminated / self.n if self.n else 0.0


def run_validation(n_incidents: int, base_seed: int, ais_config: dict, scoring_config: dict) -> dict:
    """Runs the full harness: builds the field variants once, generates
    n_incidents synthetic scenarios stratified across field variant,
    traffic density and dark-gap presence, runs elimination and all
    three scorings (baseline, F2-zeroed, F1-as-centroid-distance) on
    each, and returns the aggregated accuracy breakdown."""
    fields = build_field_variants(base_seed)
    specs = build_incident_specs(n_incidents, base_seed)

    results = [run_incident(spec, fields[spec.field_variant], ais_config, scoring_config) for spec in specs]

    overall = Accuracy()
    no_dark_overlap = Accuracy()
    centroid_baseline = Accuracy()
    by_density: dict[str, Accuracy] = {d: Accuracy() for d in TRAFFIC_DENSITY_LEVELS}

    near_miss_baseline_totals = []
    near_miss_centroid_totals = []
    for r in results:
        overall.add(r.baseline_rank, r.culprit_eliminated, r.baseline_margin)
        no_dark_overlap.add(r.no_dark_overlap_rank, r.culprit_eliminated, r.no_dark_overlap_margin)
        centroid_baseline.add(r.centroid_baseline_rank, r.culprit_eliminated, r.centroid_baseline_margin)
        by_density[r.spec.traffic_density].add(r.baseline_rank, r.culprit_eliminated, r.baseline_margin)
        if r.near_miss_baseline_total is not None and r.near_miss_centroid_total is not None:
            near_miss_baseline_totals.append(r.near_miss_baseline_total)
            near_miss_centroid_totals.append(r.near_miss_centroid_total)

    near_miss_summary = {
        "n": len(near_miss_baseline_totals),
        "mean_baseline_total": sum(near_miss_baseline_totals) / len(near_miss_baseline_totals) if near_miss_baseline_totals else None,
        "mean_centroid_total": sum(near_miss_centroid_totals) / len(near_miss_centroid_totals) if near_miss_centroid_totals else None,
    }

    return {
        "n_incidents": n_incidents,
        "results": results,
        "overall": overall,
        "by_density": by_density,
        "near_miss": near_miss_summary,
        "ablation_no_dark_overlap": no_dark_overlap,
        "ablation_centroid_baseline": centroid_baseline,
    }
