import type { OriginFieldJSON } from "../types";
import { hexToRgb } from "./tokens";
import { COLORS } from "./tokens";

const OIL_RGB = hexToRgb(COLORS.oil);

// Rasterises one time slice of the origin probability field into a
// canvas the size of the field's own grid, one texel per cell.
//
// Drawn as a texture rather than as one GeoJSON polygon per cell because
// the field is a density, and hard-edged 1 km squares read as a mosaic
// of discrete claims rather than as a continuous probability. The GPU's
// bilinear filter smooths between cell centres when the texture is
// magnified, which is the honest interpolation here: it invents no mass,
// it just stops the display quantising what the ensemble produced.
//
// The geometry stays exact. The texture's texel centres line up with the
// field's cell centres, so `fieldRasterBounds` places it on precisely the
// ground the field covers. Nothing is stretched to look bigger.
export function fieldSliceToCanvas(
  field: OriginFieldJSON,
  timeIndex: number,
  alphaFor: (prob: number) => number,
): HTMLCanvasElement | null {
  const slice = field.grid[timeIndex];
  if (!slice) return null;

  const height = field.lat.length;
  const width = field.lon.length;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;

  const ctx = canvas.getContext("2d");
  if (!ctx) return null;

  const image = ctx.createImageData(width, height);
  for (let yi = 0; yi < height; yi++) {
    // field.lat runs south to north, image rows run north to south.
    const row = slice[height - 1 - yi];
    for (let xi = 0; xi < width; xi++) {
      const o = (yi * width + xi) * 4;
      image.data[o] = OIL_RGB[0];
      image.data[o + 1] = OIL_RGB[1];
      image.data[o + 2] = OIL_RGB[2];
      image.data[o + 3] = Math.round(alphaFor(row[xi]));
    }
  }
  ctx.putImageData(image, 0, 0);
  return canvas;
}

// Outer edges of the field's cells: the lat/lon arrays are cell centres,
// so the raster extends half a step past each end.
export function fieldRasterBounds(field: OriginFieldJSON): [number, number, number, number] {
  const latStep = field.lat.length > 1 ? field.lat[1] - field.lat[0] : 0.01;
  const lonStep = field.lon.length > 1 ? field.lon[1] - field.lon[0] : 0.01;
  return [
    field.lon[0] - lonStep / 2,
    field.lat[0] - latStep / 2,
    field.lon[field.lon.length - 1] + lonStep / 2,
    field.lat[field.lat.length - 1] + latStep / 2,
  ];
}
