import type { AISPointJSON, DemoBundle, OriginFieldJSON, VesselJSON } from "../types";

// Mirrors the shape of services.core.ais.tracks.position_at: linear
// interpolation between the two bracketing pings. Good enough for the
// short great-circle legs in the demo scenario, no need to replicate the
// backend's great-circle interpolation pixel for pixel on the client.
export function positionAt(points: AISPointJSON[], tsMs: number): [number, number] | null {
  if (points.length === 0) return null;
  if (tsMs <= new Date(points[0].ts).getTime()) return [points[0].lon, points[0].lat];
  const last = points[points.length - 1];
  if (tsMs >= new Date(last.ts).getTime()) return [last.lon, last.lat];

  for (let i = 0; i < points.length - 1; i++) {
    const t0 = new Date(points[i].ts).getTime();
    const t1 = new Date(points[i + 1].ts).getTime();
    if (t0 <= tsMs && tsMs <= t1) {
      const frac = t1 === t0 ? 0 : (tsMs - t0) / (t1 - t0);
      const lon = points[i].lon + (points[i + 1].lon - points[i].lon) * frac;
      const lat = points[i].lat + (points[i + 1].lat - points[i].lat) * frac;
      return [lon, lat];
    }
  }
  return [last.lon, last.lat];
}

export function isDarkAt(vessel: VesselJSON, tsMs: number): boolean {
  return vessel.dark_gaps.some((g) => {
    const start = new Date(g.start).getTime();
    const end = new Date(g.end).getTime();
    return tsMs >= start && tsMs <= end;
  });
}

// Splits a track's points into path segments, breaking (not drawing
// through) each dark gap, so the gap reads as a real absence of data
// rather than an interpolated line.
export function trackSegments(vessel: VesselJSON): [number, number][][] {
  const gapRanges = vessel.dark_gaps.map((g) => [new Date(g.start).getTime(), new Date(g.end).getTime()] as const);
  const segments: [number, number][][] = [];
  let current: [number, number][] = [];

  for (const p of vessel.points) {
    const t = new Date(p.ts).getTime();
    const inGap = gapRanges.some(([s, e]) => t > s && t < e);
    if (inGap) {
      if (current.length > 1) segments.push(current);
      current = [];
      continue;
    }
    current.push([p.lon, p.lat]);
  }
  if (current.length > 1) segments.push(current);
  return segments;
}

export function fieldMaxProb(field: OriginFieldJSON): number {
  let max = 0;
  for (const slice of field.grid) {
    for (const row of slice) {
      for (const v of row) if (v > max) max = v;
    }
  }
  return max;
}

export function bboxCenter(bbox: [number, number, number, number]): [number, number] {
  return [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2];
}

export type Bounds = [number, number, number, number];

function growToInclude(b: Bounds, lon: number, lat: number): void {
  b[0] = Math.min(b[0], lon);
  b[1] = Math.min(b[1], lat);
  b[2] = Math.max(b[2], lon);
  b[3] = Math.max(b[3], lat);
}

// Expands bounds by a fraction of their own span, with a floor so a
// degenerate (single point) box still gets a sane camera.
export function padBounds(b: Bounds, fraction: number, minSpanDeg = 0.005): Bounds {
  const padLon = Math.max((b[2] - b[0]) * fraction, minSpanDeg);
  const padLat = Math.max((b[3] - b[1]) * fraction, minSpanDeg);
  return [b[0] - padLon, b[1] - padLat, b[2] + padLon, b[3] + padLat];
}

function fieldAndSceneBounds(bundle: DemoBundle): Bounds {
  const b: Bounds = [...bundle.scene.bbox];
  for (const lon of bundle.origin_field.lon) growToInclude(b, lon, b[1]);
  for (const lat of bundle.origin_field.lat) growToInclude(b, b[0], lat);
  return b;
}

// Just the SAR scene footprint: the "look at the slick" camera.
export function sceneBounds(bundle: DemoBundle): Bounds {
  return [...bundle.scene.bbox];
}

// The default camera: the scene footprint and the origin probability
// field, and nothing else.
//
// Everything else in the case is an order of magnitude larger. A vessel
// track runs for hours, a 52 minute dark period's reachable envelope is
// over 100 km across, and an eliminated vessel can be 250 km away, which
// is often exactly why it was eliminated. Fitting any of them shrinks
// the field to a smudge and the slick to a few pixels.
//
// So they are all still drawn, and they all run off the edge of this
// frame. Tracks entering from offscreen and an envelope arc too big to
// contain say something true about the scales involved. The "Traffic"
// view frames them when that is what is being discussed.
export function caseBounds(bundle: DemoBundle): Bounds {
  return fieldAndSceneBounds(bundle);
}

// Union of the scene bbox, the field's lat/lon extent and every AIS
// point, eliminated vessels included.
export function overallBounds(bundle: DemoBundle): Bounds {
  const b = fieldAndSceneBounds(bundle);
  for (const vessel of bundle.vessels) {
    for (const p of vessel.points) growToInclude(b, p.lon, p.lat);
  }
  return b;
}
