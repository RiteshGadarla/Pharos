import { BitmapLayer, GeoJsonLayer, LineLayer, PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { PathStyleExtension } from "@deck.gl/extensions";
import { MapboxOverlay } from "@deck.gl/mapbox";
import * as maplibregl from "maplibre-gl";
import { scalePow } from "d3-scale";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  type Bounds,
  overallBounds,
  padBounds,
  positionAt,
  trackSegments,
} from "../lib/geo";
import { fieldRasterBounds, fieldSliceMax, fieldSliceToCanvas } from "../lib/fieldRaster";
import { buildGraticule } from "../lib/graticule";
import { COLORS, hexToRgb } from "../lib/tokens";
import type { DemoBundle, VesselJSON } from "../types";

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

export interface LayerToggles {
  scene: boolean;
  detections: boolean;
  field: boolean;
  traffic: boolean;
}

// The scene PNG comes from the core service when it is up and from the
// static copy in public/data when it is not, matching how api.ts loads
// the bundle itself. Resolved once at module load, not per render.
const SCENE_PREVIEW_SRC = "/api/scene_preview.png";
const SCENE_PREVIEW_FALLBACK_SRC = "/data/scene_preview.png";

function vesselColor(vessel: VesselJSON, culpritMmsi: string): [number, number, number] {
  if (vessel.status === "eliminated") return CLEARED_RGB;
  if (vessel.mmsi === culpritMmsi) return SUSPECT_RGB;
  return MUTED_RGB;
}

function gateFillColor(verdict: string): [number, number, number, number] {
  if (verdict === "accept") return [...OIL_RGB, 160];
  if (verdict === "downgrade") return [...OIL_RGB, 80];
  return [...MUTED_RGB, 60]; // suppress: greyed
}

interface Props {
  bundle: DemoBundle;
  timeMs: number;
  timeIndex: number;
  toggles: LayerToggles;
  viewBounds: Bounds;
  hoveredMmsi: string | null;
  selectedMmsi: string | null;
  onHoverVessel: (mmsi: string | null) => void;
  onSelectVessel: (mmsi: string | null) => void;
}

export default function MapView({
  bundle,
  timeMs,
  timeIndex,
  toggles,
  viewBounds,
  hoveredMmsi,
  selectedMmsi,
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
  const sliceMax = useMemo(() => fieldSliceMax(bundle.origin_field, timeIndex), [bundle.origin_field, timeIndex]);
  const alphaScale = useMemo(
    () => scalePow().exponent(0.7).domain([0, sliceMax || 1]).range([0, 165]).clamp(true),
    [sliceMax],
  );
  const graticule = useMemo(() => buildGraticule(extent, viewBounds), [extent, viewBounds]);
  const fieldCanvas = useMemo(
    () => fieldSliceToCanvas(bundle.origin_field, timeIndex, alphaScale),
    [bundle.origin_field, timeIndex, alphaScale],
  );

  // Same live-then-static fallback as api.ts: the scene PNG is served by
  // the core service in dev and copied into public/data by `make
  // seed-demo` for the fully offline path.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(SCENE_PREVIEW_SRC, { method: "HEAD" });
        if (!cancelled) setSceneImageSrc(res.ok ? SCENE_PREVIEW_SRC : SCENE_PREVIEW_FALLBACK_SRC);
        return;
      } catch {
        // core service not running, fall through to the static copy
      }
      if (!cancelled) setSceneImageSrc(SCENE_PREVIEW_FALLBACK_SRC);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BLANK_STYLE,
      bounds: [
        [viewBounds[0], viewBounds[1]],
        [viewBounds[2], viewBounds[3]],
      ],
      fitBoundsOptions: { padding: 60 },
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
  // run, since the map constructor above already framed it.
  const didFitRef = useRef(false);
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!didFitRef.current) {
      didFitRef.current = true;
      return;
    }
    map.fitBounds(
      [
        [viewBounds[0], viewBounds[1]],
        [viewBounds[2], viewBounds[3]],
      ],
      { padding: 60, duration: 900 },
    );
  }, [viewBounds]);

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
        getColor: [...GRATICULE_RGB, 220],
        getSize: 10,
        fontFamily: '"IBM Plex Mono", monospace',
        getTextAnchor: "start",
        getAlignmentBaseline: "top",
        getPixelOffset: [4, 4],
      }),
    );

    if (toggles.field && fieldCanvas) {
      layers.push(
        new BitmapLayer({
          id: "origin-field",
          image: fieldCanvas,
          bounds: fieldRasterBounds(bundle.origin_field),
          // Below the tracks and the detection outline, above the scene.
          // The field is context for those, not a foreground element.
          opacity: 1,
          pickable: false,
        }),
      );
    }

    if (toggles.traffic) {
      const trackData: { path: [number, number][]; color: [number, number, number]; mmsi: string }[] = [];
      const gapLineData: { path: [number, number][]; mmsi: string }[] = [];
      const envelopeFeatures: GeoJSON.Feature[] = [];

      for (const vessel of bundle.vessels) {
        const color = vesselColor(vessel, bundle.culprit_mmsi);
        const isFocused = vessel.mmsi === hoveredMmsi || vessel.mmsi === selectedMmsi;
        for (const seg of trackSegments(vessel)) {
          trackData.push({ path: seg, color: isFocused ? PAPER_RGB : color, mmsi: vessel.mmsi });
        }
        for (const gap of vessel.dark_gaps) {
          envelopeFeatures.push({
            type: "Feature",
            geometry: gap.envelope,
            properties: { mmsi: vessel.mmsi, kind: "dark-envelope" },
          });
          gapLineData.push({ path: [gap.entry_point, gap.exit_point], mmsi: vessel.mmsi });
        }
      }

      layers.push(
        new GeoJsonLayer({
          id: "dark-envelopes",
          data: { type: "FeatureCollection", features: envelopeFeatures } as any,
          filled: true,
          stroked: true,
          getFillColor: [...SUSPECT_RGB, 30],
          getLineColor: [...SUSPECT_RGB, 200],
          lineWidthMinPixels: 2,
          getDashArray: [4, 3],
          dashJustified: true,
          extensions: [new PathStyleExtension({ dash: true })],
        }),
        new PathLayer({
          id: "ais-tracks",
          data: trackData,
          getPath: (d) => d.path,
          getColor: (d) => [...d.color, 220],
          getWidth: (d) => (d.mmsi === bundle.culprit_mmsi ? 3 : 2),
          widthMinPixels: 2,
          pickable: true,
          onHover: (info) => onHoverVessel(info.object ? info.object.mmsi : null),
          onClick: (info) => onSelectVessel(info.object ? info.object.mmsi : null),
          updateTriggers: { getColor: [hoveredMmsi, selectedMmsi] },
        }),
        new PathLayer({
          id: "dark-gap-lines",
          data: gapLineData,
          getPath: (d) => d.path,
          getColor: [...SUSPECT_RGB, 230],
          getWidth: 2,
          widthMinPixels: 2,
          getDashArray: [3, 2],
          dashJustified: true,
          extensions: [new PathStyleExtension({ dash: true })],
        }),
      );

      const positions = bundle.vessels
        .map((v) => ({ vessel: v, pos: positionAt(v.points, timeMs) }))
        .filter((d): d is { vessel: VesselJSON; pos: [number, number] } => d.pos !== null);

      layers.push(
        new ScatterplotLayer({
          id: "vessel-positions",
          data: positions,
          getPosition: (d) => d.pos,
          getFillColor: (d) => [...vesselColor(d.vessel, bundle.culprit_mmsi), 255],
          getLineColor: [...PAPER_RGB, 255],
          getLineWidth: 1,
          stroked: true,
          getRadius: (d) => (d.vessel.mmsi === bundle.culprit_mmsi ? 60 : 40),
          radiusMinPixels: 4,
          radiusMaxPixels: 12,
          pickable: true,
          onHover: (info) => onHoverVessel(info.object ? info.object.vessel.mmsi : null),
          onClick: (info) => onSelectVessel(info.object ? info.object.vessel.mmsi : null),
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
        if (layer?.id === "detections") {
          const g = object.properties.gate;
          return {
            html: `<div style="font-family:monospace;font-size:11px">verdict: ${g.verdict}<br/>${g.reason}</div>`,
          };
        }
        return null;
      },
    });
  }, [
    bundle,
    timeIndex,
    timeMs,
    toggles,
    sceneImageSrc,
    fieldCanvas,
    hoveredMmsi,
    selectedMmsi,
    graticule,
    onHoverVessel,
    onSelectVessel,
  ]);

  return <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />;
}
