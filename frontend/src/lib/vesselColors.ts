import { COLORS, hexToRgb, hslToRgb } from "./tokens";
import { rankOf } from "./vessel";
import type { DemoBundle } from "../types";

export type RGB = [number, number, number];

// Rank 1, 2 and 3, in order — the only hand-validated, reserved identity
// colours (see the comment on COLORS.suspect2 in tokens.ts). Everyone
// else draws from the generated wheel below.
export const RANK_RGB: RGB[] = [hexToRgb(COLORS.suspect), hexToRgb(COLORS.suspect2), hexToRgb(COLORS.suspect3)];

// Hues already claimed elsewhere on this page — suspect, suspect2,
// suspect3, oil, radar, current, forecast, wind, in that order — so a
// generated background colour is never mistaken for one of these
// deliberate ones.
const RESERVED_HUES = [350, 213, 53, 33, 196, 198, 277, 114];
const HUE_GUARD_DEG = 18;

function farFromReserved(hue: number): boolean {
  return RESERVED_HUES.every((r) => Math.min(Math.abs(hue - r), 360 - Math.abs(hue - r)) >= HUE_GUARD_DEG);
}

// `count` hues, evenly spread across whatever part of the wheel is not
// already claimed by a reserved colour. If a scene needs more room than
// is left outside those bands, the guard is dropped rather than
// clumping every extra vessel into the remaining sliver.
function backgroundHues(count: number): number[] {
  if (count <= 0) return [];
  const candidates: number[] = [];
  for (let deg = 0; deg < 360; deg++) if (farFromReserved(deg)) candidates.push(deg);
  const wheel = candidates.length >= count ? candidates : Array.from({ length: 360 }, (_, i) => i);
  return Array.from({ length: count }, (_, i) => wheel[Math.floor((i / count) * wheel.length)]);
}

// Every vessel's colour, keyed by mmsi. Rank 1-3 keep their own
// hand-validated colour; everyone else — almost always the eliminated
// majority — draws a colour off the generated wheel, evenly spread so
// two vessels that end up next to each other on the map are unlikely to
// share a hue. Built once per bundle rather than looked up per vessel,
// since the wheel's spacing depends on how many background vessels
// there are. The map and the vessel table both call this, so a track
// and its row are always the same colour.
export function buildVesselColors(bundle: DemoBundle): Map<string, RGB> {
  const colors = new Map<string, RGB>();
  const background: string[] = [];
  for (const vessel of bundle.vessels) {
    const rank = rankOf(bundle, vessel.mmsi);
    if (rank !== null && rank <= RANK_RGB.length) colors.set(vessel.mmsi, RANK_RGB[rank - 1]);
    else background.push(vessel.mmsi);
  }
  const hues = backgroundHues(background.length);
  background.forEach((mmsi, i) => colors.set(mmsi, hslToRgb(hues[i], 58, 56)));
  return colors;
}

export function rgbToCss([r, g, b]: RGB): string {
  return `rgb(${r}, ${g}, ${b})`;
}
