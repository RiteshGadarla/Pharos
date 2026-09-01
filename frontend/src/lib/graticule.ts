// A minimal graticule: parallels and meridians at a step sized to the
// current bbox, with monospaced coordinate labels, so the chart-paper
// direction (PLAN.md section 12) reads even over a blank offline
// basemap with no tile source.

function niceStep(span: number): number {
  const raw = span / 4;
  const candidates = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1];
  return candidates.find((c) => c >= raw) ?? 1;
}

export interface GraticuleLine {
  path: [number, number][];
  label: string;
  labelPos: [number, number];
}

// `extent` is how far the rules are drawn, `view` is what the camera is
// actually showing. They differ because the camera zooms between view
// presets: the rules have to reach across the whole scenario, but their
// spacing and their labels have to suit the frame on screen, or a
// zoomed-in view gets one rule and no labels.
export function buildGraticule(
  extent: [number, number, number, number],
  view: [number, number, number, number] = extent,
): GraticuleLine[] {
  const [minLon, minLat, maxLon, maxLat] = extent;
  const padLon = (maxLon - minLon) * 0.15;
  const padLat = (maxLat - minLat) * 0.15;
  const lonStep = niceStep(view[2] - view[0]);
  const latStep = niceStep(view[3] - view[1]);

  const lines: GraticuleLine[] = [];

  const lonStart = Math.ceil((minLon - padLon) / lonStep) * lonStep;
  for (let lon = lonStart; lon <= maxLon + padLon; lon += lonStep) {
    lines.push({
      path: [
        [lon, minLat - padLat],
        [lon, maxLat + padLat],
      ],
      label: `${lon.toFixed(3)}°E`,
      // Pinned to the visible frame's lower edge, not the extent's, so
      // labels stay on screen at every view preset.
      labelPos: [lon, view[1]],
    });
  }

  const latStart = Math.ceil((minLat - padLat) / latStep) * latStep;
  for (let lat = latStart; lat <= maxLat + padLat; lat += latStep) {
    lines.push({
      path: [
        [minLon - padLon, lat],
        [maxLon + padLon, lat],
      ],
      label: `${lat.toFixed(3)}°N`,
      labelPos: [view[0], lat],
    });
  }

  return lines;
}
