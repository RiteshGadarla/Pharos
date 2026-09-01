import { useMemo } from "react";
import { type Bounds, caseBounds, overallBounds, padBounds, sceneBounds } from "./geo";
import type { DemoBundle } from "../types";

// Named for the three views in PLAN.md section 12: scene, origin,
// traffic. They exist because the case spans two very different scales.
// The slick is about 5 km across, the reachable envelope of a 52 minute
// dark period is over 100 km, and no single camera shows both usefully.
export type ViewKey = "scene" | "origin" | "traffic";

export interface ViewPreset {
  key: ViewKey;
  label: string;
  title: string;
  bounds: Bounds;
}

// Three fixed cameras rather than leaving the presenter to pinch and
// drag on stage. Origin is the default: it is the view the whole tool
// exists to produce, and it is the one frame where the slick and the
// probability field are both legible at once.
export function useViewPresets(bundle: DemoBundle): ViewPreset[] {
  return useMemo(
    () => [
      {
        key: "scene",
        label: "Scene",
        title: "The SAR scene footprint and the slick detected on it.",
        bounds: padBounds(sceneBounds(bundle), 0.45),
      },
      {
        key: "origin",
        label: "Origin",
        title: "The scene and the origin probability field the backward drift produced.",
        bounds: padBounds(caseBounds(bundle), 0.35),
      },
      {
        key: "traffic",
        label: "Traffic",
        title: "Every vessel in the window, their dark period envelopes, and the vessels eliminated far offscene.",
        bounds: padBounds(overallBounds(bundle), 0.05),
      },
    ],
    [bundle],
  );
}
