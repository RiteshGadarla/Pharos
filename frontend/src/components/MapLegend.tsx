import { useState } from "react";
import type { LayerToggles } from "./MapView";
import type { StageKey } from "../lib/stages";
import { COLORS } from "../lib/tokens";

interface Props {
  stage: StageKey;
  toggles: LayerToggles;
  hasForecast: boolean;
  hasForcing: boolean;
}

// What is on the map, and what each mark MEANS.
//
// This replaced a column of coloured squares captioned "oil / origin
// field", "rank 1 suspect", "eliminated". Those name the thing without
// explaining it, which is fine for someone who built the pipeline and
// useless for a room seeing it once. A dashed ring around a vessel is
// not self-evidently "everywhere it could have reached while its
// transponder was off"; it looks like a circle.
//
// So every row here carries a sentence, and the sample is drawn in SVG
// with the same treatment the map uses, so a dashed line in the legend
// is the same dashed line on the chart. Rows appear only when the layer
// they describe is actually switched on: a legend describing something
// that is not on screen is worse than no legend.

// The heading names the question the stage is answering, so the legend
// reads as part of the argument rather than as a key bolted to the side
// of a chart.
const HEADINGS: Record<StageKey, string> = {
  acquisition: "What the sensor saw",
  drift: "What the physics says",
  attribution: "What you are looking at",
};

type Sample = "solid" | "dashed" | "ring" | "dot" | "hollow-dot" | "ring-hollow" | "arrow" | "field" | "forecast";

interface Row {
  sample: Sample;
  color: string;
  label: string;
  meaning: string;
}

function rowsFor(t: LayerToggles, hasForecast: boolean, hasForcing: boolean): Row[] {
  const rows: Row[] = [];

  if (t.detections) {
    rows.push({
      sample: "field",
      color: COLORS.oil,
      label: "Slick",
      meaning: "The oil the satellite detected, at the moment it was imaged.",
    });
  }
  if (t.field) {
    rows.push({
      sample: "field",
      color: COLORS.oil,
      label: "Origin field",
      meaning:
        "Where the oil could have come from, at the time on the scrubber. Brighter is more probable. This is what the ranking reads.",
    });
  }
  if (t.forecast && hasForecast) {
    rows.push({
      sample: "forecast",
      color: COLORS.forecast,
      label: "Forecast field",
      meaning: "Where the oil goes next. A response product, never used to rank anyone.",
    });
  }

  if (t.traffic) {
    rows.push(
      {
        sample: "solid",
        color: COLORS.muted,
        label: "Reported track",
        meaning: "Positions the vessel actually broadcast. Solid means observed.",
      },
      {
        sample: "dashed",
        color: COLORS.suspect,
        label: "Track while dark",
        meaning:
          "Estimated run between the last report and the next one. Dashed means reconstructed, not observed.",
      },
      {
        sample: "ring",
        color: COLORS.suspect,
        label: "Reachable while dark",
        meaning:
          "Everywhere the vessel could have got to during the silence, at its maximum plausible speed. Not where it was.",
      },
      {
        sample: "dot",
        color: COLORS.suspect,
        label: "Rank 1 suspect",
        meaning: "Highest scoring vessel. A ranking, not an identification.",
      },
      {
        sample: "dot",
        color: COLORS.muted,
        label: "Other survivor",
        meaning: "Still a candidate, scored below rank 1.",
      },
      {
        sample: "dot",
        color: COLORS.cleared,
        label: "Eliminated",
        meaning: "Ruled out by a stated rule. Hover the track for the written reason.",
      },
      {
        sample: "hollow-dot",
        color: COLORS.muted,
        label: "Hollow marker",
        meaning: "The vessel is dark at this instant, so this position is inferred rather than reported.",
      },
    );
  }

  if (t.radar) {
    rows.push(
      {
        sample: "dot",
        color: COLORS.radar,
        label: "Unmatched radar target",
        meaning: "A hull the SAR image shows that no AIS message accounts for, at the acquisition instant only.",
      },
      {
        sample: "ring-hollow",
        color: COLORS.radar,
        label: "Matched radar target",
        meaning: "A hull the image shows that AIS does account for. Shown as the control: a check that matches nothing is broken.",
      },
    );
  }

  if (hasForcing && t.current) {
    rows.push({
      sample: "arrow",
      color: COLORS.current,
      label: "Surface current",
      meaning: "Water movement that carried the oil. Arrow points the way it flows, length is speed.",
    });
  }
  if (hasForcing && t.wind) {
    rows.push({
      sample: "arrow",
      color: COLORS.wind,
      label: "10 m wind",
      meaning: "Air movement. Pushes the slick at roughly 3 percent of wind speed, and it is why the gate has a valid window.",
    });
  }

  return rows;
}

function SampleMark({ sample, color }: { sample: Sample; color: string }) {
  const common = { width: 26, height: 14 };
  switch (sample) {
    case "solid":
      return (
        <svg {...common} aria-hidden="true">
          <line x1="1" y1="7" x2="25" y2="7" stroke={color} strokeWidth="2.5" />
        </svg>
      );
    case "dashed":
      return (
        <svg {...common} aria-hidden="true">
          <line x1="1" y1="7" x2="25" y2="7" stroke={color} strokeWidth="2.5" strokeDasharray="4 3" />
        </svg>
      );
    case "ring":
      return (
        <svg {...common} aria-hidden="true">
          <circle cx="13" cy="7" r="6" fill={color} fillOpacity="0.18" stroke={color} strokeWidth="1.5" strokeDasharray="3 2" />
        </svg>
      );
    case "dot":
      return (
        <svg {...common} aria-hidden="true">
          <circle cx="13" cy="7" r="4.5" fill={color} />
        </svg>
      );
    case "hollow-dot":
      return (
        <svg {...common} aria-hidden="true">
          <circle cx="13" cy="7" r="4.5" fill={COLORS.ink} stroke={color} strokeWidth="2" />
        </svg>
      );
    case "ring-hollow":
      return (
        <svg {...common} aria-hidden="true">
          <circle cx="13" cy="7" r="5" fill="none" stroke={color} strokeWidth="2" />
        </svg>
      );
    case "arrow":
      return (
        <svg {...common} aria-hidden="true">
          <line x1="2" y1="7" x2="21" y2="7" stroke={color} strokeWidth="1.8" />
          <polyline points="17,3.5 21,7 17,10.5" fill="none" stroke={color} strokeWidth="1.8" />
        </svg>
      );
    case "field":
    case "forecast":
      return (
        <svg {...common} aria-hidden="true">
          <defs>
            <linearGradient id={`lg-${sample}-${color.slice(1)}`} x1="0" x2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.08" />
              <stop offset="100%" stopColor={color} stopOpacity="0.75" />
            </linearGradient>
          </defs>
          <rect x="1" y="2" width="24" height="10" rx="2" fill={`url(#lg-${sample}-${color.slice(1)})`} />
        </svg>
      );
  }
}

export default function MapLegend({ stage, toggles, hasForecast, hasForcing }: Props) {
  const [open, setOpen] = useState(true);
  const rows = rowsFor(toggles, hasForecast, hasForcing);
  if (rows.length === 0) return null;

  return (
    <div className={`map-legend ${open ? "" : "collapsed"}`}>
      <button className="map-legend-toggle" onClick={() => setOpen((o) => !o)}>
        <span>{HEADINGS[stage]}</span>
        <span className="map-legend-chevron">{open ? "–" : "+"}</span>
      </button>
      {open && (
        <div className="map-legend-rows">
          {rows.map((r) => (
            <div className="map-legend-row" key={r.label}>
              <span className="map-legend-sample">
                <SampleMark sample={r.sample} color={r.color} />
              </span>
              <span className="map-legend-text">
                <span className="map-legend-label">{r.label}</span>
                <span className="map-legend-meaning">{r.meaning}</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
