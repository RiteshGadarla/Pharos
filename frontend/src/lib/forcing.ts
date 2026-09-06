import type { ForcingJSON } from "../types";

// Reading the forcing grid for display. See backend forcing.py.
//
// Nearest neighbour throughout, never interpolated. The backend
// subsamples rather than resamples so that every value on screen is one
// the forcing file actually holds; interpolating here would undo that on
// the last step and put invented numbers under a provenance chip.

export interface Arrow {
  lon: number;
  lat: number;
  // Metres per second.
  speed: number;
  // Degrees clockwise from north, the direction the vector points
  // TOWARDS. Wind is conventionally reported as the direction it blows
  // FROM and current as the direction it sets TOWARDS, which reliably
  // confuses people, so both use "towards" here and every label in the
  // UI says the word.
  towardDeg: number;
}

export interface Reading {
  windSpeed: number | null;
  windTowardDeg: number | null;
  currentSpeed: number | null;
  currentTowardDeg: number | null;
  sstC: number | null;
  airTempC: number | null;
  at: string | null;
}

export function nearestTimeIndex(forcing: ForcingJSON, ms: number): number {
  let best = 0;
  let bestDelta = Infinity;
  for (let i = 0; i < forcing.time.length; i++) {
    const d = Math.abs(new Date(forcing.time[i]).getTime() - ms);
    if (d < bestDelta) {
      bestDelta = d;
      best = i;
    }
  }
  return best;
}

function towardDeg(u: number, v: number): number {
  return (((Math.atan2(u, v) * 180) / Math.PI) + 360) % 360;
}

// Every grid cell as an arrow, for one instant. `stride` thins the grid
// further when the camera is zoomed out far enough that every cell would
// overlap its neighbour.
export function arrowsAt(
  forcing: ForcingJSON,
  ms: number,
  which: "wind" | "current",
  stride = 1,
): Arrow[] {
  const u = which === "wind" ? forcing.wind_u : forcing.current_u;
  const v = which === "wind" ? forcing.wind_v : forcing.current_v;
  if (!u || !v) return [];

  const ti = nearestTimeIndex(forcing, ms);
  const uSlice = u[ti];
  const vSlice = v[ti];
  if (!uSlice || !vSlice) return [];

  const out: Arrow[] = [];
  for (let yi = 0; yi < forcing.lat.length; yi += stride) {
    for (let xi = 0; xi < forcing.lon.length; xi += stride) {
      const uu = uSlice[yi]?.[xi];
      const vv = vSlice[yi]?.[xi];
      if (uu === undefined || vv === undefined) continue;
      out.push({
        lon: forcing.lon[xi],
        lat: forcing.lat[yi],
        speed: Math.hypot(uu, vv),
        towardDeg: towardDeg(uu, vv),
      });
    }
  }
  return out;
}

// The forcing at one point and instant, for the panel readout.
export function readingAt(forcing: ForcingJSON, lat: number, lon: number, ms: number): Reading {
  const ti = nearestTimeIndex(forcing, ms);
  const yi = nearestIndex(forcing.lat, lat);
  const xi = nearestIndex(forcing.lon, lon);

  const cell = (block: number[][][] | null): number | null => {
    const value = block?.[ti]?.[yi]?.[xi];
    return value === undefined ? null : value;
  };

  const wu = cell(forcing.wind_u);
  const wv = cell(forcing.wind_v);
  const cu = cell(forcing.current_u);
  const cv = cell(forcing.current_v);

  return {
    at: forcing.time[ti] ?? null,
    windSpeed: wu !== null && wv !== null ? Math.hypot(wu, wv) : null,
    windTowardDeg: wu !== null && wv !== null ? towardDeg(wu, wv) : null,
    currentSpeed: cu !== null && cv !== null ? Math.hypot(cu, cv) : null,
    currentTowardDeg: cu !== null && cv !== null ? towardDeg(cu, cv) : null,
    sstC: cell(forcing.sst_c),
    airTempC: cell(forcing.air_temp_c),
  };
}

function nearestIndex(values: number[], target: number): number {
  let best = 0;
  let bestDelta = Infinity;
  for (let i = 0; i < values.length; i++) {
    const d = Math.abs(values[i] - target);
    if (d < bestDelta) {
      bestDelta = d;
      best = i;
    }
  }
  return best;
}

// Peak speed across the whole run, so arrow length can be scaled against
// a fixed reference instead of against whatever happens to be on screen.
// Scaling per frame would make a calm hour look as windy as a gale, which
// is exactly the thing an arrow layer is supposed to show.
export function peakSpeed(forcing: ForcingJSON, which: "wind" | "current"): number {
  const u = which === "wind" ? forcing.wind_u : forcing.current_u;
  const v = which === "wind" ? forcing.wind_v : forcing.current_v;
  if (!u || !v) return 1;
  let max = 0;
  for (let t = 0; t < u.length; t++) {
    for (let y = 0; y < u[t].length; y++) {
      for (let x = 0; x < u[t][y].length; x++) {
        const s = Math.hypot(u[t][y][x], v[t][y][x]);
        if (s > max) max = s;
      }
    }
  }
  return max || 1;
}

// Spacing of the forcing grid in degrees, which is what an arrow's
// length has to be measured against.
//
// Sizing arrows off the viewport instead produced arrows several times
// longer than the distance between them: every arrow overlapped its
// neighbours, the field read as scribble, and zooming out made it worse
// rather than better. A quiver arrow must never outrun its own cell.
export function gridSpacingDeg(forcing: ForcingJSON): number {
  const latStep = forcing.lat.length > 1 ? Math.abs(forcing.lat[1] - forcing.lat[0]) : 0.2;
  const lonStep = forcing.lon.length > 1 ? Math.abs(forcing.lon[1] - forcing.lon[0]) : 0.2;
  return Math.min(latStep, lonStep);
}

// Arrow geometry in lon/lat: a shaft along the bearing plus two barbs.
//
// Built as a path rather than drawn with an icon so it scales with the
// map and stays correct under the projection at any zoom. Length is
// proportional to speed against the run's own peak, so a short arrow
// means slow rather than merely far away, and capped at the grid
// spacing so the fastest arrow still stops short of its neighbour.
export function arrowPath(
  arrow: Arrow,
  maxSpeed: number,
  maxLengthDeg: number,
  // Shifts the whole arrow off its grid point, in cells. Wind and current
  // are sampled at the same coordinates and here often oppose each other,
  // so drawn from a common origin each pair fused into a single
  // double-headed mark that read as one arrow pointing both ways.
  // Staggering the two families by half a cell separates them.
  offsetCells: [number, number] = [0, 0],
): [number, number][] {
  const frac = Math.min(1, arrow.speed / (maxSpeed || 1));
  // A floor on length so a near-calm cell still shows its direction
  // rather than collapsing to a dot the eye reads as missing data.
  const len = maxLengthDeg * (0.25 + 0.75 * frac);
  const rad = (arrow.towardDeg * Math.PI) / 180;
  const latScale = Math.cos((arrow.lat * Math.PI) / 180) || 1;

  const dLat = Math.cos(rad) * len;
  const dLon = (Math.sin(rad) * len) / latScale;

  // Centred on the grid point rather than starting from it. An arrow
  // that starts at its cell and runs a full length outward reaches into
  // the next cell and is read as belonging there; centring keeps each
  // arrow over the point whose value it reports.
  const baseLat = arrow.lat - dLat / 2 + offsetCells[1] * maxLengthDeg;
  const baseLon = arrow.lon - dLon / 2 + (offsetCells[0] * maxLengthDeg) / latScale;

  const tipLat = baseLat + dLat;
  const tipLon = baseLon + dLon;

  const head = len * 0.35;
  const barb = (angleOffset: number): [number, number] => {
    const a = rad + Math.PI + angleOffset;
    return [tipLon + (Math.sin(a) * head) / latScale, tipLat + Math.cos(a) * head];
  };

  return [
    [baseLon, baseLat],
    [tipLon, tipLat],
    barb(Math.PI / 7),
    [tipLon, tipLat],
    barb(-Math.PI / 7),
  ];
}
