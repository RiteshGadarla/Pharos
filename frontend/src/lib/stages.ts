import type { DemoBundle } from "../types";
import type { LayerToggles } from "../components/MapView";
import type { ViewKey } from "./views";

// The demo runs as three stages, in order, each answering one question.
//
// The console this replaced put every layer on screen at once behind
// toggles, which is the right tool for an operator who already knows
// what they are looking at and the wrong one for a room seeing it for
// the first time. Everything arriving together reads as decoration.
// Arriving in order, it reads as an argument: here is the image, here
// is what the physics says about it, and only then, here is the vessel
// that answer implicates.
//
// Nothing is hidden by a stage that is not also computed. Every stage
// reads the same precomputed bundle; a stage only decides which parts
// of it are on screen and what the caption claims. The layer toggles
// stay live inside every stage, so any layer can be pulled forward if
// the room asks.

export type StageKey = "acquisition" | "drift" | "attribution";

// What the scrubber spans in this stage. "none" hides it: stage 1 is a
// single instant, the acquisition, and a time control there would imply
// the SAR image is a movie. "forward" and "full" only exist once there
// is a forecast field to scrub into.
export type TimelineMode = "none" | "backward" | "full";

export type SidePanel = "scene" | "drift" | "attribution";

// One number from the bundle and what it counts, for the rail. The
// answer sentence says the same thing in prose; the facts are what a
// room can read from the back of it.
export interface StageFact {
  value: string;
  label: string;
}

export interface Stage {
  key: StageKey;
  ordinal: number;
  label: string;
  // The question the stage answers, shown above the map. Kept as a
  // question because the answer below it is the thing being claimed,
  // and a claim needs its question visible to be judged.
  question: string;
  // The claim, filled from the bundle's own numbers. Never hardcoded
  // prose about what the demo "would" show.
  answer: (bundle: DemoBundle) => string;
  facts: (bundle: DemoBundle) => StageFact[];
  layers: LayerToggles;
  view: ViewKey;
  timeline: TimelineMode;
  panel: SidePanel;
}

const ALL_OFF: LayerToggles = {
  scene: false,
  detections: false,
  field: false,
  forecast: false,
  traffic: false,
  radar: false,
  current: false,
  wind: false,
};

function fmtHours(h: number): string {
  const rounded = Math.round(h);
  return `${rounded} hour${rounded === 1 ? "" : "s"}`;
}

// The horizon the run covered. `span_hours` is what the drift kernel
// actually produced; falling back to the time coordinate overstates it
// by half a bin, which is how a 48 hour hindcast comes to be captioned
// as 49. See backend hindcast/field.py.
export function fieldSpanHours(field: { t_min: string; t_max: string; span_hours?: number }): number {
  if (typeof field.span_hours === "number" && field.span_hours > 0) return field.span_hours;
  return Math.abs(new Date(field.t_max).getTime() - new Date(field.t_min).getTime()) / 3_600_000;
}

function backwardHours(bundle: DemoBundle): number {
  return fieldSpanHours(bundle.origin_field);
}

function forwardHours(bundle: DemoBundle): number {
  return bundle.forecast_field ? fieldSpanHours(bundle.forecast_field) : 0;
}

// The estimated age as a RANGE. PLAN.md's non-goals rule out absolute
// slick age in hours from a single acquisition, so the answer line says
// a band and never a figure.
function ageRange(b: DemoBundle): string {
  const w = b.origin_window;
  const band = b.slick_features.age_band;
  if (!w) return band;
  return `${band}, ${w.earliest_hours_before.toFixed(0)} to ${w.latest_hours_before.toFixed(0)} h old`;
}

export const STAGES: Stage[] = [
  {
    key: "acquisition",
    ordinal: 1,
    label: "Acquisition",
    question: "What did the satellite actually see?",
    answer: (b) => {
      const primary = b.detections.find((d) => d.detection_id === b.primary_detection_id);
      const gate = primary?.gate;
      const area = b.slick_features.area_km2.toFixed(2);
      const wind = gate ? gate.wind_speed_ms.toFixed(1) : "unknown";
      return (
        `One Sentinel-1 scene acquired ${formatUtc(b.scene.acquired_at)} UTC. ` +
        `${b.detections.length} candidate polygon${b.detections.length === 1 ? "" : "s"}, ` +
        `the primary one ${area} km2, estimated ${ageRange(b)}. ` +
        `Wind at the slick was ${wind} m/s, so the wind gate returned ${gate?.verdict ?? "no verdict"}.`
      );
    },
    facts: (b) => {
      const primary = b.detections.find((d) => d.detection_id === b.primary_detection_id);
      const w = b.origin_window;
      const facts: StageFact[] = [
        { value: `${formatUtc(b.scene.acquired_at)} UTC`, label: "acquired" },
        { value: String(b.detections.length), label: b.detections.length === 1 ? "candidate" : "candidates" },
        { value: `${b.slick_features.area_km2.toFixed(2)} km²`, label: "primary slick" },
        {
          value: w ? `${w.earliest_hours_before.toFixed(0)} to ${w.latest_hours_before.toFixed(0)} h` : b.slick_features.age_band,
          label: w ? `old, ${b.slick_features.age_band}` : "age band",
        },
      ];
      if (primary) {
        facts.push({ value: `${primary.gate.wind_speed_ms.toFixed(1)} m/s`, label: `wind, gate ${primary.gate.verdict}` });
      }
      return facts;
    },
    layers: { ...ALL_OFF, scene: true, detections: true },
    view: "scene",
    timeline: "none",
    panel: "scene",
  },
  {
    key: "drift",
    ordinal: 2,
    label: "Drift",
    question: "Where did it come from, and where is it going?",
    answer: (b) => {
      const f = b.origin_field;
      const back = fmtHours(backwardHours(b));
      const fwd = b.forecast_field ? fmtHours(forwardHours(b)) : null;
      const forwardClause = fwd
        ? ` The same kernel run forwards from the same particles gives ${fwd} of forecast, which is a response planning product and never an input to the ranking.`
        : "";
      return (
        `${f.n_members} independent ${f.kernel} members, each with its own sampled wind drift, ` +
        `current error and diffusivity, run ${back} backwards from the slick. ` +
        `The result is a probability of origin over space and time that sums to 1 and is never ` +
        `collapsed to a single point.${forwardClause}`
      );
    },
    facts: (b) => {
      const facts: StageFact[] = [
        { value: String(b.origin_field.n_members), label: `${b.origin_field.kernel ?? "drift"} members` },
        { value: `${Math.round(backwardHours(b))} h`, label: "run backwards" },
      ];
      if (b.forecast_field) {
        facts.push({ value: `${Math.round(forwardHours(b))} h`, label: "forecast, never ranked" });
      }
      facts.push({ value: "Σ = 1", label: "a probability field, never a point" });
      return facts;
    },
    // The forcing comes on here and nowhere else by default. This is
    // the stage that asks where the oil went, and the wind and current
    // arrows are the answer to the question the field immediately
    // raises: why does it lean that way.
    layers: {
      ...ALL_OFF,
      scene: true,
      detections: true,
      field: true,
      forecast: true,
      current: true,
      wind: true,
    },
    // The only stage that has to hold both fields at once, and they
    // reach in opposite directions from the slick.
    view: "drift",
    timeline: "full",
    panel: "drift",
  },
  {
    key: "attribution",
    ordinal: 3,
    label: "Attribution",
    question: "Which vessel was in the origin field when it mattered?",
    answer: (b) => {
      const survivors = b.suspects.length;
      const eliminated = b.eliminations.length;
      const verdict = b.verdict?.verdict ?? "RANKED";
      const top = b.suspects[0];
      const lead = top
        ? `${top.mmsi} ranks first at ${top.total.toFixed(3)}`
        : "no vessel survived elimination";
      // Says what is on the map, not just what the numbers are. The
      // stage's hardest job is getting a room from "lines and circles"
      // to "tracks and reachable sets", and the caption is the first
      // thing they read.
      const darkCount = b.vessels.filter((v) => v.dark_gaps.length > 0).length;
      return (
        `${survivors + eliminated} vessels crossed the window. ${eliminated} eliminated, each with a written ` +
        `reason. Of the ${survivors} that survive, ${lead}. Verdict class: ${verdict}. ` +
        `Solid lines are positions the vessels broadcast; dashed lines and shaded rings are the ` +
        `${darkCount} that stopped broadcasting, showing the reconstruction rather than an observation. ` +
        `Click any vessel to follow it alone.`
      );
    },
    facts: (b) => {
      const top = b.suspects[0];
      const facts: StageFact[] = [
        { value: String(b.suspects.length + b.eliminations.length), label: "vessels in the window" },
        { value: String(b.eliminations.length), label: "eliminated, with reasons" },
        { value: String(b.suspects.length), label: "survive" },
      ];
      if (top) facts.push({ value: top.mmsi, label: `ranks first at ${top.total.toFixed(2)}` });
      facts.push({ value: (b.verdict?.verdict ?? "RANKED").replace("_", " "), label: "verdict" });
      return facts;
    },
    // Forcing off: the attribution stage already carries tracks,
    // envelopes, radar targets and a probability field, and arrows on
    // top of that is where a chart stops being readable. It stays one
    // click away in the layer panel.
    layers: { ...ALL_OFF, scene: true, detections: true, field: true, traffic: true, radar: true },
    view: "traffic",
    timeline: "backward",
    panel: "attribution",
  },
];

export function stageAt(index: number): Stage {
  return STAGES[Math.min(STAGES.length - 1, Math.max(0, index))];
}

function formatUtc(iso: string): string {
  return new Date(iso).toISOString().slice(0, 16).replace("T", " ");
}
