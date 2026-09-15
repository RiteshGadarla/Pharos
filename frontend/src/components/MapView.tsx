import { BitmapLayer, GeoJsonLayer, LineLayer, PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { PathStyleExtension } from "@deck.gl/extensions";
import { MapboxOverlay } from "@deck.gl/mapbox";
import * as maplibregl from "maplibre-gl";
import { scalePow } from "d3-scale";
import { useEffect, useMemo, useRef, useState } from "react";
import { firstAvailable } from "../api";
import {
  type Bounds,
  overallBounds,
  padBounds,
  positionAt,
} from "../lib/geo";
import { arrowPath, arrowsAt, gridSpacingDeg, peakSpeed } from "../lib/forcing";
import {
  darkMidpoint,
  darkReachKm,
  deadReckonedPath,
  headingAt,
  isDarkGapActive,
  rankOf,
  reportedSegments,
  vesselRole,
  vesselSummary,
} from "../lib/vessel";
import { fieldRasterBounds, fieldSliceMax, fieldSliceToCanvas } from "../lib/fieldRaster";
import { buildGraticule } from "../lib/graticule";
import { frameField, type TimelineFrame } from "../lib/timeline";
import { COLORS, hexToRgb } from "../lib/tokens";
import type { DemoBundle, ShipTargetJSON, VesselJSON } from "../types";

const BLANK_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": COLORS.ink } }],
};

const OIL_RGB = hexToRgb(COLORS.oil);
const SUSPECT_RGB = hexToRgb(COLORS.suspect);
const CLEARED_RGB = hexToRgb(COLORS.cleared);
const MUTED_RGB = hexToRgb(COLORS.muted);
const PAPER_RGB = hexToRgb(COLORS.paper);
const GRATICULE_RGB = hexToRgb(COLORS.graticule);
const RADAR_RGB = hexToRgb(COLORS.radar);
const CURRENT_RGB = hexToRgb(COLORS.current);
const WIND_RGB = hexToRgb(COLORS.wind);

// Screen space the map chrome covers, in pixels, so a view preset frames
// its data in the part of the map nobody has put a card over.
export interface FitPadding {
  top: number;
  right: number;
  bottom: number;
  left: number;
}


interface LabelCandidate {
  vessel: VesselJSON;
  pos: [number, number];
  rank: number | null;
}

// Where each vessel label goes, as pixels below its default spot. Screen positions are estimated from the framed view rather than
// read back from the map, which is exact enough to tell two labels apart
// and needs no redraw when the camera eases between presets.
function stackLabels(
  items: LabelCandidate[],
  view: { bounds: Bounds; padding: FitPadding; width: number; height: number; selectedMmsi: string | null },
): Map<string, number> {
  const rows = new Map<string, number>();
  const w = view.width - view.padding.left - view.padding.right;
  const h = view.height - view.padding.top - view.padding.bottom;
  if (w <= 0 || h <= 0) return rows;
  const [west, south, east, north] = view.bounds;
  const mercY = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
  const spanX = ((east - west) * Math.PI) / 180;
  const spanY = mercY(north) - mercY(south);
  const scale = Math.min(w / spanX, h / spanY);
  const cx = view.padding.left + w / 2;
  const cy = view.padding.top + h / 2;
  const midX = (((east + west) / 2) * Math.PI) / 180;
  const midY = (mercY(north) + mercY(south)) / 2;

  const priority = (d: LabelCandidate) => (d.vessel.mmsi === view.selectedMmsi ? -1 : (d.rank ?? 1000));
  const placed: { x0: number; y0: number; x1: number; y1: number }[] = [];
  for (const d of [...items].sort((a, b) => priority(a) - priority(b))) {
    const x = cx + ((d.pos[0] * Math.PI) / 180 - midX) * scale + 12;
    const y = cy - (mercY(d.pos[1]) - midY) * scale + 6;
    const text = d.rank ? `#${d.rank}  ${d.vessel.mmsi}` : d.vessel.mmsi;
    // Matches the label sizes below: 16 px for the selected vessel, 13
    // for the rest, in a monospace face with its background padding.
    const size = d.vessel.mmsi === view.selectedMmsi ? 16 : 13;
    const boxW = text.length * size * 0.62 + 10;
    const boxH = size + 8;
    let shift = 0;
    for (let tries = 0; tries < 8; tries++) {
      const b = { x0: x, y0: y + shift, x1: x + boxW, y1: y + shift + boxH };
      const hit = placed.filter((p) => b.x0 < p.x1 && b.x1 > p.x0 && b.y0 < p.y1 && b.y1 > p.y0);
      if (hit.length === 0) break;
      shift = Math.max(...hit.map((p) => p.y1)) - y + 2;
    }
    placed.push({ x0: x, y0: y + shift, x1: x + boxW, y1: y + shift + boxH });
    rows.set(d.vessel.mmsi, shift);
  }
  return rows;
}

export interface LayerToggles {
  scene: boolean;
  detections: boolean;
  // The backward origin field: where the slick came from.
  field: boolean;
  // The forward forecast field: where it goes next. A separate toggle
  // from `field` and not a mode of it, because the two answer different
  // questions and only one of them is evidence.
  forecast: boolean;
  traffic: boolean;
  radar: boolean;
  // Surface current and 10 m wind, subsampled from the same NetCDF the
  // drift ensemble integrated. Context for why the origin field leans
  // the way it does, never an input to the ranking.
  current: boolean;
  wind: boolean;
}


function vesselColor(vessel: VesselJSON, culpritMmsi: string | null): [number, number, number] {
  const role = vesselRole(vessel, culpritMmsi);
  if (role === "eliminated") return CLEARED_RGB;
  if (role === "culprit") return SUSPECT_RGB;
  return MUTED_RGB;
}

// How strongly to draw a vessel given what is selected.
//
// Selecting one vessel dims the rest hard rather than merely
// highlighting the chosen one. With five tracks, two envelopes and a
// probability field on screen at once, a highlight is lost; taking the
// others down to a fifth is what actually isolates the one being
// discussed, and every one of them is a click away from coming back.
function vesselAlpha(mmsi: string, selected: string | null, hovered: string | null): number {
  if (!selected) return mmsi === hovered ? 255 : 215;
  if (mmsi === selected) return 255;
  return 55;
}

function gateFillColor(verdict: string): [number, number, number, number] {
  if (verdict === "accept") return [...OIL_RGB, 160];
  if (verdict === "downgrade") return [...OIL_RGB, 80];
  return [...MUTED_RGB, 60]; // suppress: greyed
}

interface Props {
  bundle: DemoBundle;
  timeMs: number;
  // Which drift field owns the current instant, and where in it. The
  // map draws exactly one field: the backward origin field up to the
  // acquisition instant, the forward forecast after it. See
  // lib/timeline.ts for why the two are never blended.
  frame: TimelineFrame;
  toggles: LayerToggles;
  viewBounds: Bounds;
  fitPadding: FitPadding;
  hoveredMmsi: string | null;
  selectedMmsi: string | null;
  // Where the scene PNG may be, most live first: the core service when it
  // is up, the static copy when it is not, each for the case on screen.
  // See api.ts scenePreviewCandidates.
  previewUrls: string[];
  onHoverVessel: (mmsi: string | null) => void;
  onSelectVessel: (mmsi: string | null) => void;
}

export default function MapView({
  bundle,
  timeMs,
  frame,
  toggles,
  viewBounds,
  fitPadding,
  hoveredMmsi,
  selectedMmsi,
  previewUrls,
  onHoverVessel,
  onSelectVessel,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const [sceneImageSrc, setSceneImageSrc] = useState<string | null>(null);

  const extent = useMemo(() => padBounds(overallBounds(bundle), 0.1), [bundle]);
  // Normalised against this slice's own peak, not the whole volume's.
  // See fieldSliceMax for why, and for what the UI does to keep that
  // choice from hiding the drop in density it trades away.
  //
  // Compressed so the low-mass tail of the distribution stays visible
  // instead of being crushed to nothing by the peak, but not as hard as
  // a square root, which lifts the tail enough to wash the SAR scene
  // orange from edge to edge. Capped well below opaque for the same
  // reason: the field sits over the scene and has to let it through.
  // The field this instant belongs to, and whether it is the evidence
  // or the forecast. Exactly one of them is live at any frame.
  const activeField = useMemo(() => frameField(bundle, frame), [bundle, frame]);
  const fieldVisible = frame.direction === "backward" ? toggles.field : toggles.forecast;

  const sliceMax = useMemo(
    () => (activeField ? fieldSliceMax(activeField, frame.index) : 0),
    [activeField, frame.index],
  );
  const alphaScale = useMemo(
    () => scalePow().exponent(0.7).domain([0, sliceMax || 1]).range([0, 165]).clamp(true),
    [sliceMax],
  );
  const graticule = useMemo(() => buildGraticule(extent, viewBounds), [extent, viewBounds]);
  const fieldCanvas = useMemo(
    () => (activeField ? fieldSliceToCanvas(activeField, frame.index, alphaScale) : null),
    [activeField, frame.index, alphaScale],
  );

  // Same live-then-static fallback as api.ts: the scene PNG is served by
  // the core service in dev and copied into public/data by `make
  // seed-demo` for the fully offline path. Joined into a key so a new
  // array with the same URLs does not refetch.
  const previewKey = previewUrls.join("|");
  useEffect(() => {
    let cancelled = false;
    firstAvailable(previewKey.split("|")).then((src) => {
      if (!cancelled) setSceneImageSrc(src);
    });
    return () => {
      cancelled = true;
    };
  }, [previewKey]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BLANK_STYLE,
      bounds: [
        [viewBounds[0], viewBounds[1]],
        [viewBounds[2], viewBounds[3]],
      ],
      fitBoundsOptions: { padding: fitPadding },
      attributionControl: false,
      dragRotate: false,
      touchPitch: false,
    });
    const overlay = new MapboxOverlay({ interleaved: false, layers: [] });
    map.addControl(overlay);
    mapRef.current = map;
    overlayRef.current = overlay;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Eased fly to whichever view preset is active. Skips the very first
  // run, since the map constructor above already framed it. The padding
  // is compared by value: a new object with the same numbers is not a
  // reason to move the camera.
  const paddingKey = `${fitPadding.top},${fitPadding.right},${fitPadding.bottom},${fitPadding.left}`;
  const didFitRef = useRef(false);
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!didFitRef.current) {
      didFitRef.current = true;
      return;
    }
    // The pane may have just changed size under the map: stage 1 draws
    // no scrubber, so stepping from it to stage 3 shortens the map in the
    // same render that changes the view. Fitting against the stale size
    // framed the traffic view for a taller map and cut off its bottom.
    map.resize();
    map.fitBounds(
      [
        [viewBounds[0], viewBounds[1]],
        [viewBounds[2], viewBounds[3]],
      ],
      { padding: fitPadding, duration: 900 },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewBounds, paddingKey]);

  useEffect(() => {
    const overlay = overlayRef.current;
    if (!overlay) return;

    const layers = [];

    // Bottom of the stack: the SAR scene the detections were made on, so
    // the polygons sit on the image they came from rather than floating
    // over blank water.
    const preview = bundle.scene.preview;
    if (toggles.scene && preview && sceneImageSrc) {
      const [w, s, e, n] = preview.bounds;
      layers.push(
        new BitmapLayer({
          id: "sar-scene",
          image: sceneImageSrc,
          bounds: preview.bounds,
        }),
        // The scene is a 5 km square inside a case that spans over 100 km.
        // Zoomed out it is a small pale rectangle, and without a rule
        // around it that reads as a rendering artifact rather than as the
        // footprint of the acquisition everything else derives from.
        new PathLayer({
          id: "scene-footprint",
          data: [
            {
              path: [
                [w, s],
                [e, s],
                [e, n],
                [w, n],
                [w, s],
              ],
            },
          ],
          getPath: (d: { path: [number, number][] }) => d.path,
          getColor: [...GRATICULE_RGB, 220],
          getWidth: 1,
          widthMinPixels: 1,
        }),
      );
    }

    layers.push(
      new LineLayer({
        id: "graticule",
        data: graticule,
        getSourcePosition: (d) => d.path[0],
        getTargetPosition: (d) => d.path[1],
        getColor: [...GRATICULE_RGB, 130],
        getWidth: 1,
      }),
      new TextLayer({
        id: "graticule-labels",
        data: graticule,
        getPosition: (d) => d.labelPos,
        getText: (d) => d.label,
        getColor: [...GRATICULE_RGB, 230],
        getSize: 12,
        fontFamily: '"IBM Plex Mono", monospace',
        getTextAnchor: "start",
        getAlignmentBaseline: "top",
        getPixelOffset: [4, 4],
      }),
    );

    // Forcing arrows sit under every finding, above only the scene and
    // the graticule. They are the chart the case is drawn on: the water
    // and air that moved the oil. Drawing them over the tracks would
    // make context compete with evidence.
    const forcing = bundle.forcing;
    if (forcing && (toggles.current || toggles.wind)) {
      // Arrow length is scaled against the run's own peak, not against
      // whatever is on screen this frame. Per-frame scaling would make a
      // calm hour look identical to a gale, which is the one thing an
      // arrow layer exists to distinguish.
      //
      // The cap is the grid spacing, not the viewport: an arrow longer
      // than the distance to its neighbour overlaps it, and a field of
      // overlapping arrows is a texture rather than a reading.
      const arrowSpanDeg = gridSpacingDeg(forcing) * 0.72;
      if (toggles.current) {
        const arrows = arrowsAt(forcing, timeMs, "current");
        const peak = peakSpeed(forcing, "current");
        layers.push(
          new PathLayer({
            id: "current-arrows",
            data: arrows,
            getPath: (d) => arrowPath(d, peak, arrowSpanDeg),
            getColor: [...CURRENT_RGB, 120],
            getWidth: 1.4,
            widthMinPixels: 1.4,
            widthMaxPixels: 3,
            pickable: true,
            updateTriggers: { getPath: [timeMs, arrowSpanDeg] },
          }),
        );
      }
      if (toggles.wind) {
        const arrows = arrowsAt(forcing, timeMs, "wind");
        const peak = peakSpeed(forcing, "wind");
        layers.push(
          new PathLayer({
            id: "wind-arrows",
            data: arrows,
            // Offset half a cell so wind does not sit on top of current.
            getPath: (d) => arrowPath(d, peak, arrowSpanDeg * 0.8, [0.35, 0.35]),
            getColor: [...WIND_RGB, 105],
            getWidth: 1.2,
            widthMinPixels: 1.2,
            widthMaxPixels: 3,
            pickable: true,
            updateTriggers: { getPath: [timeMs, arrowSpanDeg] },
          }),
        );
      }
    }

    if (fieldVisible && fieldCanvas && activeField) {
      layers.push(
        new BitmapLayer({
          // Two ids, not one with a changing image: deck.gl keeps a
          // layer's texture across prop updates, and reusing the id
          // across a direction change makes the origin field flash in
          // the forecast's colour for a frame as the scrubber crosses
          // the acquisition instant.
          id: frame.direction === "backward" ? "origin-field" : "forecast-field",
          image: fieldCanvas,
          bounds: fieldRasterBounds(activeField),
          // Below the tracks and the detection outline, above the scene.
          // The field is context for those, not a foreground element.
          opacity: 1,
          pickable: false,
        }),
      );
    }

    if (toggles.traffic) {
      // Reported track and dark run are built as separate layers with
      // separate styling, because the difference between them is the
      // most important thing on this map. A solid line is a position the
      // vessel broadcast. A dashed line is a position nobody recorded
      // and this system reconstructed. Drawn alike, a reconstruction
      // reads as evidence.
      const reported: { path: [number, number][]; mmsi: string }[] = [];
      const reckoned: { path: [number, number][]; mmsi: string }[] = [];
      const envelopeFeatures: GeoJSON.Feature[] = [];
      const darkMarkers: { pos: [number, number]; mmsi: string; reachKm: number; mins: number }[] = [];

      for (const vessel of bundle.vessels) {
        for (const seg of reportedSegments(vessel)) {
          reported.push({ path: seg, mmsi: vessel.mmsi });
        }
        for (const gap of vessel.dark_gaps) {
          reckoned.push({ path: deadReckonedPath(gap), mmsi: vessel.mmsi });
          darkMarkers.push({
            pos: darkMidpoint(gap),
            mmsi: vessel.mmsi,
            reachKm: darkReachKm(gap),
            mins: gap.duration_min,
          });
          // The envelope is the largest thing on the map and it swamped
          // everything when every vessel showed one at once. With a
          // vessel selected only that vessel's is drawn; with none
          // selected they are all drawn faintly, so the room can see
          // there are several before being shown one.
          const dimmed = selectedMmsi !== null && selectedMmsi !== vessel.mmsi;
          if (dimmed) continue;
          envelopeFeatures.push({
            type: "Feature",
            geometry: gap.envelope,
            properties: {
              mmsi: vessel.mmsi,
              kind: "dark-envelope",
              mins: Math.round(gap.duration_min),
              reachKm: Math.round(darkReachKm(gap)),
              focused: selectedMmsi === vessel.mmsi,
            },
          });
        }
      }

      const envelopeAlpha = selectedMmsi ? 44 : 20;
      layers.push(
        new GeoJsonLayer({
          id: "dark-envelopes",
          data: { type: "FeatureCollection", features: envelopeFeatures } as any,
          filled: true,
          stroked: true,
          getFillColor: [...SUSPECT_RGB, envelopeAlpha],
          getLineColor: (f: any) => [...SUSPECT_RGB, f.properties.focused ? 220 : 120],
          lineWidthMinPixels: 2,
          getDashArray: [4, 3],
          dashJustified: true,
          extensions: [new PathStyleExtension({ dash: true })],
          pickable: true,
          updateTriggers: { getFillColor: [selectedMmsi], getLineColor: [selectedMmsi] },
        }),
        new PathLayer({
          id: "ais-tracks",
          data: reported,
          getPath: (d) => d.path,
          getColor: (d) => {
            const v = bundle.vessels.find((x) => x.mmsi === d.mmsi)!;
            return [...vesselColor(v, bundle.culprit_mmsi), vesselAlpha(d.mmsi, selectedMmsi, hoveredMmsi)];
          },
          getWidth: (d) =>
            d.mmsi === selectedMmsi ? 4 : d.mmsi === bundle.culprit_mmsi ? 3 : 2,
          widthMinPixels: 2,
          pickable: true,
          onHover: (info) => onHoverVessel(info.object ? info.object.mmsi : null),
          onClick: (info) => onSelectVessel(info.object ? info.object.mmsi : null),
          updateTriggers: {
            getColor: [hoveredMmsi, selectedMmsi],
            getWidth: [selectedMmsi],
          },
        }),
        new PathLayer({
          id: "dark-reckoned-path",
          data: reckoned,
          getPath: (d) => d.path,
          // Cream, not the vessel's own colour. It sits inside the
          // red-tinted envelope, where red dashes are invisible, and it
          // is an annotation on the chart rather than a measurement on
          // it: this line is what the system inferred, and it should not
          // be drawn in the same ink as what the vessel reported.
          getColor: (d) => [...PAPER_RGB, vesselAlpha(d.mmsi, selectedMmsi, hoveredMmsi)],
          getWidth: (d) => (d.mmsi === selectedMmsi ? 3 : 2),
          widthMinPixels: 2,
          getDashArray: [3, 3],
          dashJustified: true,
          extensions: [new PathStyleExtension({ dash: true })],
          pickable: true,
          onHover: (info) => onHoverVessel(info.object ? info.object.mmsi : null),
          onClick: (info) => onSelectVessel(info.object ? info.object.mmsi : null),
          updateTriggers: { getColor: [hoveredMmsi, selectedMmsi], getWidth: [selectedMmsi] },
        }),
        // A question mark at the point of maximum ignorance: furthest in
        // time from the last reported position and the next one. It is
        // the label the dashed line needs to stop reading as a track.
        new TextLayer({
          id: "dark-midpoint-markers",
          data: darkMarkers,
          getPosition: (d) => d.pos,
          getText: () => "?",
          getColor: (d) => [...PAPER_RGB, vesselAlpha(d.mmsi, selectedMmsi, hoveredMmsi)],
          getSize: 15,
          fontFamily: '"IBM Plex Mono", monospace',
          fontWeight: 700,
          getTextAnchor: "middle",
          getAlignmentBaseline: "center",
          pickable: true,
          onHover: (info) => onHoverVessel(info.object ? info.object.mmsi : null),
          updateTriggers: { getColor: [hoveredMmsi, selectedMmsi] },
        }),
      );

      const positions = bundle.vessels
        .map((v) => ({
          vessel: v,
          pos: positionAt(v.points, timeMs),
          heading: headingAt(v.points, timeMs),
          dark: v.dark_gaps.some((g) => isDarkGapActive(g, timeMs)),
          rank: rankOf(bundle, v.mmsi),
        }))
        .filter((d): d is typeof d & { pos: [number, number] } => d.pos !== null);

      // Vessels close together at one instant would otherwise print their
      // MMSIs over each other into an unreadable smear. Labels are placed
      // in priority order (the selected vessel, then by rank, then the
      // eliminated) and any that would land on one already placed drops
      // a row. Nothing is hidden: every vessel keeps its label.
      const labelRows = stackLabels(positions, {
        bounds: viewBounds,
        padding: fitPadding,
        width: containerRef.current?.clientWidth ?? 0,
        height: containerRef.current?.clientHeight ?? 0,
        selectedMmsi,
      });

      layers.push(
        new ScatterplotLayer({
          id: "vessel-positions",
          data: positions,
          getPosition: (d) => d.pos,
          // A vessel dark at this instant is drawn hollow: there is no
          // report behind that dot, only a reconstruction. Filled means
          // observed, hollow means inferred, exactly as with the lines.
          filled: true,
          getFillColor: (d) =>
            d.dark
              ? [...hexToRgb(COLORS.ink), vesselAlpha(d.vessel.mmsi, selectedMmsi, hoveredMmsi)]
              : [...vesselColor(d.vessel, bundle.culprit_mmsi), vesselAlpha(d.vessel.mmsi, selectedMmsi, hoveredMmsi)],
          stroked: true,
          getLineColor: (d) => [
            ...vesselColor(d.vessel, bundle.culprit_mmsi),
            vesselAlpha(d.vessel.mmsi, selectedMmsi, hoveredMmsi),
          ],
          getLineWidth: 2,
          lineWidthMinPixels: 2,
          getRadius: (d) => (d.vessel.mmsi === bundle.culprit_mmsi ? 60 : 40),
          radiusMinPixels: 5,
          radiusMaxPixels: 13,
          pickable: true,
          onHover: (info) => onHoverVessel(info.object ? info.object.vessel.mmsi : null),
          onClick: (info) => onSelectVessel(info.object ? info.object.vessel.mmsi : null),
          updateTriggers: {
            getFillColor: [hoveredMmsi, selectedMmsi, timeMs],
            getLineColor: [hoveredMmsi, selectedMmsi],
          },
        }),
        // Heading, from the vessel's own reported course, so the eye can
        // tell which way a track is being travelled. Without it a line
        // between two points is equally a vessel arriving and one
        // leaving, and which of those it is decides the whole case.
        new TextLayer({
          id: "vessel-headings",
          data: positions.filter((d) => d.heading !== null),
          getPosition: (d) => d.pos,
          getText: () => "\u25B2",
          getAngle: (d) => -(d.heading ?? 0),
          getColor: (d) => [
            ...vesselColor(d.vessel, bundle.culprit_mmsi),
            vesselAlpha(d.vessel.mmsi, selectedMmsi, hoveredMmsi),
          ],
          getSize: 13,
          getPixelOffset: [0, -16],
          getTextAnchor: "middle",
          getAlignmentBaseline: "center",
          updateTriggers: { getColor: [hoveredMmsi, selectedMmsi], getAngle: [timeMs] },
        }),
        // The MMSI, on the map, next to the vessel. Without it the
        // ranked list on the right and the lines on the left are two
        // unconnected displays and the room has to be told which is
        // which out loud.
        new TextLayer({
          id: "vessel-labels",
          data: positions,
          getPosition: (d) => d.pos,
          getText: (d) => (d.rank ? `#${d.rank}  ${d.vessel.mmsi}` : d.vessel.mmsi),
          getColor: (d) => [
            ...(d.vessel.mmsi === selectedMmsi ? PAPER_RGB : vesselColor(d.vessel, bundle.culprit_mmsi)),
            vesselAlpha(d.vessel.mmsi, selectedMmsi, hoveredMmsi),
          ],
          getSize: (d) => (d.vessel.mmsi === selectedMmsi ? 16 : 13),
          fontFamily: '"IBM Plex Mono", monospace',
          getTextAnchor: "start",
          getAlignmentBaseline: "top",
          background: true,
          getBackgroundColor: [...hexToRgb(COLORS.ink), 190],
          backgroundPadding: [4, 2, 4, 2],
          getPixelOffset: (d) => [12, 6 + (labelRows.get(d.vessel.mmsi) ?? 0)],
          pickable: true,
          onHover: (info) => onHoverVessel(info.object ? info.object.vessel.mmsi : null),
          onClick: (info) => onSelectVessel(info.object ? info.object.vessel.mmsi : null),
          updateTriggers: {
            getColor: [hoveredMmsi, selectedMmsi],
            getSize: [selectedMmsi],
            getText: [bundle],
            getPixelOffset: [labelRows],
          },
        }),
      );
    }

    // Ship targets the SAR scene itself shows. Drawn above the tracks,
    // because the whole argument of PLAN.md section 11 is that an
    // unmatched target is an observation from a second, independent
    // sensor sitting on top of the AIS picture, not part of it.
    const radar = bundle.radar_crosscheck;
    if (toggles.radar && radar) {
      const unmatched = radar.targets.filter((t) => t.matched_mmsi === null);
      const matched = radar.targets.filter((t) => t.matched_mmsi !== null);
      layers.push(
        // Matched hulls are drawn faintly and hollow. They are the
        // control: a cross check that matches nothing is a broken
        // matcher, not a fleet of dark vessels, and you cannot see the
        // difference unless both are on screen.
        new ScatterplotLayer({
          id: "radar-targets-matched",
          data: matched,
          getPosition: (d) => d.centroid,
          filled: false,
          stroked: true,
          getLineColor: [...RADAR_RGB, 120],
          getLineWidth: 2,
          lineWidthMinPixels: 2,
          getRadius: 80,
          radiusMinPixels: 5,
          radiusMaxPixels: 11,
          pickable: true,
        }),
        new ScatterplotLayer({
          id: "radar-targets-unmatched",
          data: unmatched,
          getPosition: (d) => d.centroid,
          filled: true,
          stroked: true,
          getFillColor: [...RADAR_RGB, 210],
          getLineColor: [...PAPER_RGB, 255],
          getLineWidth: 2,
          lineWidthMinPixels: 2,
          getRadius: 110,
          radiusMinPixels: 7,
          radiusMaxPixels: 15,
          pickable: true,
        }),
      );
    }

    if (toggles.detections) {
      layers.push(
        new GeoJsonLayer({
          id: "detections",
          data: {
            type: "FeatureCollection",
            features: bundle.detections.map((d) => ({
              type: "Feature",
              geometry: d.geometry,
              properties: d,
            })),
          } as any,
          filled: true,
          stroked: true,
          getFillColor: (f: any) => gateFillColor(f.properties.gate.verdict),
          getLineColor: (f: any) =>
            f.properties.gate.verdict === "suppress" ? [...MUTED_RGB, 200] : [...OIL_RGB, 255],
          lineWidthMinPixels: 2,
          pickable: true,
        }),
      );
    }

    overlay.setProps({
      layers,
      getTooltip: ({ object, layer }: any) => {
        if (!object) return null;
        const wrap = (title: string, body: string) =>
          ({
            html:
              `<div style="font-family:'IBM Plex Mono',monospace;font-size:13px;line-height:1.5;max-width:360px">` +
              `<div style="color:${COLORS.paper};font-weight:600">${title}</div>` +
              `<div style="color:${COLORS.muted}">${body}</div></div>`,
          });

        if (layer?.id === "detections") {
          const g = object.properties.gate;
          return wrap(
            `Detection, wind gate ${g.verdict}`,
            `${g.reason}<br/>Wind ${g.wind_speed_ms.toFixed(1)} m/s at acquisition.`,
          );
        }
        if (layer?.id?.startsWith("radar-targets")) {
          const t = object as ShipTargetJSON;
          const state = t.matched_mmsi
            ? `Matched to AIS ${t.matched_mmsi} at ${Math.round(t.match_distance_m ?? 0)} m.`
            : "No AIS reported this hull at the acquisition instant. The radar image saw it, the AIS picture did not.";
          const hits = t.envelope_hits.length
            ? `<br/>Inside the dark envelope of ${t.envelope_hits.join(", ")}.`
            : "";
          return wrap(
            `Radar ship target ${t.target_id}`,
            `${t.pixel_area} px, ${t.mean_backscatter_db.toFixed(1)} dB.<br/>${state}${hits}` +
              "<br/>Radar sees one instant only: this says nothing about any other time.",
          );
        }
        if (layer?.id === "dark-envelopes") {
          const p = object.properties;
          return wrap(
            `${p.mmsi}: reachable while dark`,
            `Everywhere this vessel could have been during a ${p.mins} minute silence, ` +
              `dead-reckoned at its plausible maximum speed (about ${p.reachKm} km of reach). ` +
              "Not where it was. Where it could not be ruled out from.",
          );
        }
        if (layer?.id === "dark-reckoned-path" || layer?.id === "dark-midpoint-markers") {
          return wrap(
            `${object.mmsi}: estimated track while dark`,
            "A straight run from the last reported position to the first one after the silence. " +
              "An assumption of steady course and speed, not an observation. The shaded ring is " +
              "everywhere else it could have gone instead.",
          );
        }
        if (layer?.id === "ais-tracks") {
          const v = bundle.vessels.find((x) => x.mmsi === object.mmsi);
          return wrap(`${object.mmsi}: reported AIS track`, v ? vesselSummary(bundle, v) : "");
        }
        if (layer?.id === "vessel-positions" || layer?.id === "vessel-labels") {
          const v = object.vessel as VesselJSON;
          const where = object.dark
            ? "Dark at this instant: this position is reconstructed, not reported."
            : "Position as broadcast at this instant.";
          return wrap(
            `${v.mmsi}  ${v.vessel_type}`,
            `${where}<br/>${vesselSummary(bundle, v)}`,
          );
        }
        if (layer?.id === "current-arrows" || layer?.id === "wind-arrows") {
          const isWind = layer.id === "wind-arrows";
          return wrap(
            isWind ? "10 m wind" : "Surface current",
            `${object.speed.toFixed(2)} m/s towards ${Math.round(object.towardDeg)} degrees.<br/>` +
              "Forcing the drift ensemble integrated. Context, never scored.",
          );
        }
        return null;
      },
    });
    // fitPadding is tracked by value through paddingKey.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    bundle,
    frame,
    timeMs,
    toggles,
    activeField,
    fieldVisible,
    sceneImageSrc,
    fieldCanvas,
    hoveredMmsi,
    selectedMmsi,
    graticule,
    viewBounds,
    paddingKey,
    onHoverVessel,
    onSelectVessel,
  ]);

  return <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />;
}
