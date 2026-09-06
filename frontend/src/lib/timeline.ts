import type { DemoBundle, OriginFieldJSON } from "../types";

// One time axis across both drift fields.
//
// The backward hindcast runs from 48 hours before acquisition up to the
// acquisition instant. The forward forecast runs from acquisition out to
// its own horizon. They are two separate NetCDF grids with two separate
// time coordinates, and the demo needs them to read as one continuous
// sweep through the life of the slick: where it came from, the moment
// the satellite saw it, where it goes next.
//
// So the two are merged into a single ordered array of frames. Each
// frame names which field owns that instant and the index into it, and
// the map draws that one field at that one index. Nothing is
// interpolated between the fields and no frame belongs to both: the
// acquisition instant is the origin field's last step, because that is
// the step that carries the observation.

export type FieldDirection = "backward" | "forward";

export interface TimelineFrame {
  iso: string;
  ms: number;
  direction: FieldDirection;
  // Index into the field named by `direction`.
  index: number;
}

export interface Timeline {
  frames: TimelineFrame[];
  // Index into `frames` of the acquisition instant, the pivot the whole
  // case turns on. Always the last backward frame.
  pivot: number;
  // Width of one frame in milliseconds, from the field's own time step.
  // A frame is a time bin and its timestamp is that bin's centre, so
  // nothing on this axis resolves finer than this. The scrubber uses it
  // to decide what counts as reading "at acquisition": the bin holding
  // the acquisition instant is centred up to half a step away from it,
  // and reporting that half step as though it were a real offset from
  // the satellite pass would be precision the field does not have.
  stepMs: number;
  // The slice of `frames` that is the backward field alone, for the
  // stages that must not show the future.
  backwardRange: [number, number];
  forwardRange: [number, number] | null;
}

function fieldFrames(field: OriginFieldJSON, direction: FieldDirection): TimelineFrame[] {
  return field.time.map((iso, index) => ({
    iso,
    ms: new Date(iso).getTime(),
    direction,
    index,
  }));
}

function medianStepMs(frames: TimelineFrame[]): number {
  if (frames.length < 2) return 30 * 60_000;
  const diffs = frames.slice(1).map((f, i) => f.ms - frames[i].ms).sort((a, b) => a - b);
  return diffs[Math.floor(diffs.length / 2)];
}

export function buildTimeline(bundle: DemoBundle): Timeline {
  const backward = fieldFrames(bundle.origin_field, "backward");
  backward.sort((a, b) => a.ms - b.ms);
  const stepMs = medianStepMs(backward);

  const forecast = bundle.forecast_field;
  if (!forecast || forecast.time.length === 0) {
    return {
      frames: backward,
      pivot: backward.length - 1,
      stepMs,
      backwardRange: [0, backward.length - 1],
      forwardRange: null,
    };
  }

  const pivotMs = backward[backward.length - 1].ms;
  // The forecast's own first step sits at the acquisition instant, which
  // the backward field already owns. Dropping it keeps the axis strictly
  // increasing and keeps one instant from being drawn by two fields.
  const forward = fieldFrames(forecast, "forward")
    .sort((a, b) => a.ms - b.ms)
    .filter((f) => f.ms > pivotMs);

  const frames = [...backward, ...forward];
  const pivot = backward.length - 1;
  return {
    frames,
    pivot,
    stepMs,
    backwardRange: [0, pivot],
    forwardRange: forward.length > 0 ? [pivot + 1, frames.length - 1] : null,
  };
}

// The field a frame points at, ready to hand to the map.
export function frameField(bundle: DemoBundle, frame: TimelineFrame): OriginFieldJSON | null {
  if (frame.direction === "backward") return bundle.origin_field;
  return bundle.forecast_field ?? null;
}

// Hours from acquisition, signed: negative before, positive after.
export function hoursFromAcquisition(frame: TimelineFrame, acquiredAt: string): number {
  return (frame.ms - new Date(acquiredAt).getTime()) / 3_600_000;
}

// Fractional position of an instant along a visible slice of the axis,
// from 0 to 1, or null if it falls outside.
//
// Interpolated on FRAME INDEX, not on elapsed time, because that is what
// the slider is linear in. The merged axis joins two fields whose time
// steps need not match, so a time-linear fraction would sit slightly off
// the frame the slider actually lands on.
export function fractionAtMs(timeline: Timeline, range: [number, number], ms: number): number | null {
  const frames = timeline.frames;
  if (range[1] <= range[0]) return null;
  if (ms < frames[range[0]].ms || ms > frames[range[1]].ms) return null;

  for (let i = range[0]; i < range[1]; i++) {
    const a = frames[i].ms;
    const b = frames[i + 1].ms;
    if (ms >= a && ms <= b) {
      const within = b === a ? 0 : (ms - a) / (b - a);
      return (i - range[0] + within) / (range[1] - range[0]);
    }
  }
  return null;
}

// Where the acquisition instant falls along a visible slice of the
// axis, or null if it is outside that slice.
//
// Interpolated rather than snapped to a frame. No frame sits exactly on
// the satellite pass: a frame is a time bin, its timestamp is the bin
// centre, and the ensemble's seed time jitter shifts where those bins
// land relative to acquisition. On the demo field the nearest bin centre
// is 16 minutes late. Drawing the marker on that frame and labelling it
// "acquired" would put the one instant that was actually observed in the
// wrong place, so the marker goes where the instant is and the readout
// keeps reporting each frame's own time.
export function acquisitionFraction(
  timeline: Timeline,
  range: [number, number],
  acquiredAtMs: number,
): number | null {
  return fractionAtMs(timeline, range, acquiredAtMs);
}

// Where the age-implied origin window falls along a visible slice of the
// axis, as a [start, end] pair of fractions, or null if none of it is in
// view.
//
// A band rather than an edge because it is a band: the slick's contrast
// and complexity bound when the discharge happened, they do not date it.
// See backend scoring/age_window.py.
export function originWindowFraction(
  timeline: Timeline,
  range: [number, number],
  acquiredAtMs: number,
  earliestHoursBefore: number,
  latestHoursBefore: number,
): [number, number] | null {
  const frames = timeline.frames;
  if (range[1] <= range[0]) return null;
  const first = frames[range[0]].ms;
  const last = frames[range[1]].ms;

  // Hours before acquisition run backwards in time, so the later bound
  // is the earlier instant. Clamped into view rather than dropped: a
  // window that runs off the end of the axis is still partly visible,
  // and hiding it would understate what the age evidence covers.
  const lo = Math.max(first, acquiredAtMs - latestHoursBefore * 3_600_000);
  const hi = Math.min(last, acquiredAtMs - earliestHoursBefore * 3_600_000);
  if (hi <= lo) return null;

  const a = fractionAtMs(timeline, range, lo);
  const b = fractionAtMs(timeline, range, hi);
  if (a === null || b === null) return null;
  return [a, b];
}

// The frame whose bin centre sits closest to a given instant. Used to
// open every stage on acquisition, which is the one moment all three
// stages share and the only one that was observed rather than inferred.
export function nearestFrame(timeline: Timeline, ms: number): number {
  let best = 0;
  let bestDelta = Infinity;
  timeline.frames.forEach((f, i) => {
    const d = Math.abs(f.ms - ms);
    if (d < bestDelta) {
      bestDelta = d;
      best = i;
    }
  });
  return best;
}

// Clamps a frame index into the window a stage allows, so moving
// between stages never leaves the scrubber pointing outside its own
// track.
export function clampToRange(index: number, range: [number, number]): number {
  return Math.min(range[1], Math.max(range[0], index));
}
