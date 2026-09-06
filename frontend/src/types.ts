// Mirrors backend/services/core/schemas.py and the demo_bundle.json shape
// written by backend/scripts/seed_demo.py. See PLAN.md section 4.

export type GateVerdict = "accept" | "downgrade" | "suppress";
export type AgeBand = "fresh" | "intermediate" | "weathered";
export type VesselStatus = "survivor" | "eliminated";

// The SAR scene warped to EPSG:4326 and stretched for display, drawn as
// the map basemap. The image itself comes from /api/scene_preview.png,
// this is only where to place it. See backend/services/core/preview.py.
export interface ScenePreview {
  bounds: [number, number, number, number];
  width: number;
  height: number;
  display_db_window: [number, number];
  note: string;
}

export interface SceneMeta {
  scene_id: string;
  acquired_at: string;
  bbox: [number, number, number, number];
  crs: string;
  source_path: string;
  // Which SensorAdapter read the scene. Carried through to the dossier
  // provenance page, see PLAN.md section 5A.
  sensor?: string;
  note: string;
  preview?: ScenePreview;
}

export interface GateInfo {
  wind_speed_ms: number;
  verdict: GateVerdict;
  reason: string;
}

export interface DetectionJSON {
  detection_id: string;
  class_name: string;
  geometry: GeoJSON.Polygon;
  mean_class_prob: number;
  pixel_area: number;
  gate: GateInfo;
}

export interface SlickFeaturesJSON {
  detection_id: string;
  area_km2: number;
  perimeter_km: number;
  complexity_ratio: number;
  major_axis_deg: number;
  elongation: number;
  mean_backscatter_db: number;
  contrast_db: number;
  age_band: AgeBand;
  age_reasoning: string;
}

export interface OriginFieldJSON {
  seed: number;
  n_members: number;
  // Which DriftKernel produced this field, and from what forcing. Read
  // straight from the field's own NetCDF attributes, so the bundle
  // cannot disagree with the file.
  kernel?: string;
  forcing_source?: string;
  // Which way time ran. The two fields have identical structure, so
  // this is the only thing separating an origin field from a forecast.
  // Absent reads as backward. See backend forecast/forward.py.
  direction?: "backward" | "forward";
  // Forward fields only. A drift kernel that runs out of forcing data
  // stops quietly and simply returns fewer steps, so the horizon that
  // was achieved travels with the field rather than being assumed from
  // config. See backend forecast/forward.py.
  requested_horizon_hours?: number;
  achieved_horizon_hours?: number;
  horizon_truncated?: boolean;
  // The horizon the run actually covered. Not the same as t_max minus
  // t_min: those are bin centres and the binning runs half a step past
  // the last sample, so a 48 hour run grids as a 48.5 hour axis. Quote
  // this in any caption naming a horizon.
  span_hours?: number;
  t_min: string;
  t_max: string;
  time: string[];
  lat: number[];
  lon: number[];
  // dims (time, lat, lon), sums to 1 over the whole volume
  grid: number[][][];
}

export interface AISPointJSON {
  ts: string;
  lat: number;
  lon: number;
  sog: number;
  cog: number;
  heading: number | null;
}

export interface DarkGapJSON {
  start: string;
  end: string;
  duration_min: number;
  entry_point: [number, number];
  exit_point: [number, number];
  envelope: GeoJSON.Polygon;
}

export interface SuspectScoreJSON {
  total: number;
  factors: Record<string, number>;
  rank: number;
  narrative: string;
  // The ShipTarget id backing F8, when an unmatched radar target fell
  // inside this vessel's dark envelope over live field mass. null is
  // the ordinary case.
  radar_support?: string | null;
}

export interface IntegrityFlagJSON {
  kind: "no_imo" | "implied_speed" | "static_change" | "mmsi_reuse" | "position_jump";
  at: string;
  detail: string;
  severity: number;
}

// One hull the SAR scene itself shows. matched_mmsi null means radar
// saw something AIS did not report. See PLAN.md section 11.
export interface ShipTargetJSON {
  target_id: string;
  centroid: [number, number];
  pixel_area: number;
  mean_backscatter_db: number;
  matched_mmsi: string | null;
  match_distance_m: number | null;
  match_confidence: number;
  field_mass: number | null;
  envelope_hits: string[];
}

export interface RadarCrossCheckJSON {
  match_radius_m: number | null;
  n_targets: number;
  n_matched: number;
  n_unmatched: number;
  targets: ShipTargetJSON[];
  caveats: string[];
}

export type VerdictClass = "ATTRIBUTED" | "RANKED" | "DARK_CONFIRMED";

export interface CaseVerdictJSON {
  case_id: string;
  verdict: VerdictClass;
  reasoning: string;
  top_suspects: string[];
  unmatched_targets: string[];
  infrastructure_flag: boolean;
}

export interface OpticalCorroborationJSON {
  detection_id: string;
  status: "agree" | "disagree" | "no_coverage";
  sensor: string | null;
  acquired_at: string | null;
  delta_hours: number | null;
  reasoning: string;
}

export interface MarpolAssessmentJSON {
  mmsi: string;
  en_route: boolean | null;
  distance_to_land_nm: number | null;
  in_special_area: boolean | null;
  // A band, never a scalar: SAR cannot see slick thickness.
  est_discharge_l_per_nm: [number, number] | null;
  flag: "conditions_not_met" | "conditions_met" | "insufficient_data";
  assumptions: string[];
}

export interface InfrastructureJSON {
  flagged: boolean;
  mass_within_radius: number;
  installations: { name: string; type: string; lon: number; lat: number; mass: number }[];
  statement: string;
}

// The origin time window the slick's own condition implies, and the
// only evidence in the case about WHEN the discharge happened. The
// backward field cannot tell a 48 hour old origin from a 1 hour old
// one; the slick's contrast and complexity can, weakly. F1 and F2
// weight the field's time axis by this. See backend
// scoring/age_window.py.
export interface OriginWindowJSON {
  age_band: AgeBand;
  earliest_hours_before: number;
  latest_hours_before: number;
  taper_hours: number;
  // Never zero: the age band downweights, it never eliminates.
  floor_weight: number;
  statement: string;
  // How far past each edge of the window a vessel is still scored as
  // though it were inside it. The band comes from contrast and
  // complexity, which cannot resolve a couple of hours, so a discharge
  // that really happened at -14 h against an 0 to 12 h band is the same
  // event with a slightly wrong band, not a different one. F9 starts
  // penalising only beyond this margin.
  band_uncertainty_hours?: number;
  falloff_hours?: number;
  timing_statement?: string;
}

// One vessel's answer to "were you here at a plausible hour?", which is
// what F9 scores. See backend scoring/temporal.py.
export interface VesselTimingJSON {
  mmsi: string;
  // The hour this vessel had its best opportunity to be the source,
  // read off the unweighted field so F9 is not scoring its own
  // assumption.
  opportunity_at: string | null;
  // How close the vessel was, at that hour, to the most likely origin
  // available at that hour. A fraction in [0, 1], normalised per
  // timestep so it means the same thing at every hour.
  opportunity_alignment: number;
  lag_hours: number | null;
  // Hours outside the window AFTER the band's uncertainty is allowed
  // for. Zero means no penalty was applied at all.
  offset_hours: number | null;
  within_band: boolean | null;
  within_uncertainty: boolean | null;
  score: number;
  statement: string;
}

// Wind, current and temperature over the case window. Context for the
// drift rather than evidence: it explains why the origin field leans
// where it does, and it is never scored.
//
// Subsampled from the same NetCDF the ensemble integrated, never
// resampled, so every arrow drawn is a value the forcing file actually
// holds at that grid point and timestep. See backend forcing.py.
export interface ForcingJSON {
  time: string[];
  lat: number[];
  lon: number[];
  // All dims (time, lat, lon), matching the origin field.
  current_u: number[][][] | null;
  current_v: number[][][] | null;
  sst_c: number[][][] | null;
  wind_u: number[][][] | null;
  wind_v: number[][][] | null;
  air_temp_c: number[][][] | null;
  provenance: {
    current_source: string;
    wind_source: string;
    grid_deg: number | null;
    time_step_hours: number;
    note: string;
  };
}

// The case rebuilt one class of evidence at a time. See backend
// scoring/case_build.py.
//
// The ranking is a result and a room can only accept or reject it. This
// is the same ranking assembled in front of them, so they can see which
// evidence did the work and what happens without it.
export interface CaseStepJSON {
  key: string;
  label: string;
  question: string;
  factors_added: string[];
  factors_so_far: string[];
  ranking: { mmsi: string; total: number; rank: number }[];
  lead: string | null;
  lead_changed: boolean;
  note: string;
}

// What a simpler approach would have concluded on the same data. Each
// is a real method someone might use, named with what it assumes, and
// each can come out agreeing with us. See backend scoring/case_build.py.
export interface BaselineJSON {
  key: string;
  label: string;
  assumes: string;
  answer: string | null;
  detail: string;
  agrees: boolean;
  // Gap to the runner-up. A baseline that picks the right vessel by a
  // hair out of sixty kilometres is guessing and getting lucky.
  separation_km: number | null;
  // How far the winner actually was. A baseline can agree while its
  // winner sits 64 km away, which is proximity having nothing to say
  // and landing on the right answer regardless.
  winner_km: number | null;
}

export interface CaseBuildJSON {
  steps: CaseStepJSON[];
  final_lead: string | null;
  // The earliest step after which the leader never changes again.
  stabilises_at_step: string | null;
  // Factors whose removal alone changes who leads. Empty is the
  // strongest result: no single piece of evidence carries the case.
  decisive_factors: string[];
  statement: string;
  baselines?: BaselineJSON[];
}

export interface EliminationJSON {
  reason: string;
  rule: string;
}

export interface VesselJSON {
  mmsi: string;
  vessel_type: string;
  points: AISPointJSON[];
  dark_gaps: DarkGapJSON[];
  integrity_flags?: IntegrityFlagJSON[];
  status: VesselStatus;
  elimination: EliminationJSON | null;
  score: SuspectScoreJSON | null;
}

export interface IncidentContext {
  status: string;
  source_reference: string;
}

export interface DemoBundle {
  case_id: string;
  generated_at: string;
  status_note: string;
  incident_context: IncidentContext;
  scene: SceneMeta;
  detections: DetectionJSON[];
  primary_detection_id: string;
  slick_features: SlickFeaturesJSON;
  origin_window?: OriginWindowJSON;
  vessel_timing?: Record<string, VesselTimingJSON>;
  origin_field: OriginFieldJSON;
  // Where the slick goes next: same kernel, same seed particles,
  // positive time step. Optional because it is the first thing cut if
  // the precompute budget runs out, and the demo must still run
  // without it. Never an input to the scoring.
  forecast_field?: OriginFieldJSON;
  forcing?: ForcingJSON;
  vessels: VesselJSON[];
  eliminations: (EliminationJSON & { mmsi: string })[];
  suspects: (SuspectScoreJSON & { mmsi: string })[];
  case_build?: CaseBuildJSON;
  culprit_mmsi: string;
  optical?: OpticalCorroborationJSON;
  verdict?: CaseVerdictJSON;
  marpol?: MarpolAssessmentJSON | null;
  infrastructure?: InfrastructureJSON;
  radar_crosscheck?: RadarCrossCheckJSON;
}

export const FACTOR_LABELS: Record<string, string> = {
  field_integral: "F1 field integral",
  dark_overlap: "F2 dark overlap",
  axis_alignment: "F3 axis alignment",
  speed_anomaly: "F4 speed anomaly",
  course_anomaly: "F5 course anomaly",
  vessel_plausibility: "F6 vessel plausibility",
  ais_integrity: "F7 AIS integrity",
  radar_confirmed_dark: "F8 radar confirmed dark",
  temporal_consistency: "F9 temporal consistency",
};

// What each verdict class means, in one line, in the panel. See
// PLAN.md section 12. DARK_CONFIRMED is a finding, not a failure: every
// competing system files "no broadcasting suspect" as no result.
export const VERDICT_BLURBS: Record<VerdictClass, string> = {
  ATTRIBUTED:
    "One vessel dominates the ranking and was broadcasting throughout the origin window.",
  RANKED:
    "Several vessels remain plausible and none dominates. The ranking narrows the field.",
  DARK_CONFIRMED:
    "No broadcasting vessel is a plausible candidate, and radar saw a hull in the origin envelope that AIS never reported.",
};
