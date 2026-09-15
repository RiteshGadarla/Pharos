import type { AISPointJSON, DarkGapJSON, DemoBundle, VesselJSON } from "../types";

// What one vessel looks like on the map, and what its dark period means.
//
// The console used to draw a track as one undifferentiated line and a
// dark gap as a large dashed circle, with nothing on screen saying which
// parts were observed and which were inferred. That is the single most
// important distinction in the whole case: a solid segment is a position
// the vessel broadcast, a dashed segment is a position nobody recorded
// and the system reconstructed. Reading them as the same kind of line
// makes a reconstruction look like evidence.

export type VesselRole = "culprit" | "survivor" | "eliminated";

export function vesselRole(vessel: VesselJSON, culpritMmsi: string | null): VesselRole {
  if (vessel.status === "eliminated") return "eliminated";
  if (vessel.mmsi === culpritMmsi) return "culprit";
  return "survivor";
}

export function rankOf(bundle: DemoBundle, mmsi: string): number | null {
  return bundle.suspects.find((s) => s.mmsi === mmsi)?.rank ?? null;
}

// The dead-reckoned best estimate of where the vessel went while dark:
// a straight run from its last reported position to its first one after
// the gap.
//
// This is deliberately the simplest possible reconstruction, and the UI
// labels it as an estimate rather than a track. The honest claim is not
// "it went this way" but "if it held a steady course and speed it went
// this way, and the envelope is everywhere else it could have been
// instead". Drawing a confident curve here would assert knowledge the
// absence of data cannot support.
export function deadReckonedPath(gap: DarkGapJSON, steps = 24): [number, number][] {
  const [lon0, lat0] = gap.entry_point;
  const [lon1, lat1] = gap.exit_point;
  const out: [number, number][] = [];
  for (let i = 0; i <= steps; i++) {
    const f = i / steps;
    out.push([lon0 + (lon1 - lon0) * f, lat0 + (lat1 - lat0) * f]);
  }
  return out;
}

// Midpoint of the dark run, where the "position not observed" marker
// goes. The point of maximum ignorance: furthest in time from both the
// last reported position and the next one.
export function darkMidpoint(gap: DarkGapJSON): [number, number] {
  const [lon0, lat0] = gap.entry_point;
  const [lon1, lat1] = gap.exit_point;
  return [(lon0 + lon1) / 2, (lat0 + lat1) / 2];
}

// How far the vessel could have run while dark, in km, at its plausible
// maximum speed. This is the number that explains the size of the
// envelope, which otherwise reads as an arbitrary circle.
export function darkReachKm(gap: DarkGapJSON, maxSpeedKn = 30): number {
  return (gap.duration_min / 60) * maxSpeedKn * 1.852;
}

export function isDarkGapActive(gap: DarkGapJSON, ms: number): boolean {
  return ms >= new Date(gap.start).getTime() && ms <= new Date(gap.end).getTime();
}

// Track split into the runs AIS actually reported, breaking at each dark
// period so no line is ever drawn through an absence of data.
export function reportedSegments(vessel: VesselJSON): [number, number][][] {
  const gaps = vessel.dark_gaps.map(
    (g) => [new Date(g.start).getTime(), new Date(g.end).getTime()] as const,
  );
  const segments: [number, number][][] = [];
  let current: [number, number][] = [];

  for (const p of vessel.points) {
    const t = new Date(p.ts).getTime();
    if (gaps.some(([s, e]) => t > s && t < e)) {
      if (current.length > 1) segments.push(current);
      current = [];
      continue;
    }
    current.push([p.lon, p.lat]);
  }
  if (current.length > 1) segments.push(current);
  return segments;
}

// Course over ground at an instant, for the heading marker. Taken from
// the vessel's own reported COG where there is a ping to read it from,
// rather than differenced off the track, so the arrow shows what the
// vessel said it was doing.
export function headingAt(points: AISPointJSON[], ms: number): number | null {
  if (points.length === 0) return null;
  let best: AISPointJSON | null = null;
  let bestDelta = Infinity;
  for (const p of points) {
    const d = Math.abs(new Date(p.ts).getTime() - ms);
    if (d < bestDelta) {
      bestDelta = d;
      best = p;
    }
  }
  // More than half an hour from the nearest ping is not a heading, it is
  // a guess about one.
  if (!best || bestDelta > 30 * 60_000) return null;
  return best.heading ?? best.cog;
}

// A one-line description of what this vessel is and why it is on screen,
// for the map tooltip and the focus card.
export function vesselSummary(bundle: DemoBundle, vessel: VesselJSON): string {
  const role = vesselRole(vessel, bundle.culprit_mmsi);
  if (role === "eliminated") {
    return vessel.elimination?.reason ?? "Eliminated, no reason recorded.";
  }
  const rank = rankOf(bundle, vessel.mmsi);
  const dark = vessel.dark_gaps.length;
  const darkPart = dark
    ? ` Went dark ${dark} time${dark > 1 ? "s" : ""} during the window.`
    : " Broadcast continuously through the window.";
  return `Rank ${rank ?? "unranked"} of ${bundle.suspects.length} survivors.${darkPart}`;
}
