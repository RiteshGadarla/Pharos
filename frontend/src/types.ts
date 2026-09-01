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
  origin_field: OriginFieldJSON;
  vessels: VesselJSON[];
  eliminations: (EliminationJSON & { mmsi: string })[];
  suspects: (SuspectScoreJSON & { mmsi: string })[];
  culprit_mmsi: string;
}

export const FACTOR_LABELS: Record<string, string> = {
  field_integral: "F1 field integral",
  dark_overlap: "F2 dark overlap",
  axis_alignment: "F3 axis alignment",
  speed_anomaly: "F4 speed anomaly",
  course_anomaly: "F5 course anomaly",
  vessel_plausibility: "F6 vessel plausibility",
};
