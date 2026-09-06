import { readingAt } from "../lib/forcing";
import type { DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
  timeMs: number;
}

// Wind, current and temperature at the slick, at the instant on the
// scrubber. The numbers behind the drift.
//
// The arrows on the map show the shape of the forcing; this shows its
// magnitude, which arrows are bad at. A room can see that the current
// runs southwest without being able to say whether that is 0.05 m/s or
// half a knot, and the difference is the difference between an origin
// two kilometres away and one twenty.
//
// It also answers the obvious question the drift stage raises and never
// otherwise addresses: why does the origin field lean that way. Because
// the water was going that way, at this speed, at this time.
export default function ForcingReadout({ bundle, timeMs }: Props) {
  const forcing = bundle.forcing;
  if (!forcing) return null;

  const [w, s, e, n] = bundle.scene.bbox;
  const r = readingAt(forcing, (s + n) / 2, (w + e) / 2, timeMs);

  return (
    <div className="forcing-readout">
      <div className="forcing-head">
        <span className="forcing-title">Conditions at the slick</span>
        <span
          className="forcing-note"
          title={forcing.provenance.note}
        >
          {forcing.provenance.time_step_hours}h steps
        </span>
      </div>

      <div className="forcing-grid">
        <Cell
          label="Current"
          value={r.currentSpeed !== null ? `${r.currentSpeed.toFixed(2)} m/s` : "n/a"}
          bearing={r.currentTowardDeg}
          swatch="current"
          title="Surface current at the slick. The water that carried the oil. Bearing is the direction it flows towards."
        />
        <Cell
          label="Wind"
          value={r.windSpeed !== null ? `${r.windSpeed.toFixed(1)} m/s` : "n/a"}
          bearing={r.windTowardDeg}
          swatch="wind"
          title="10 m wind. Pushes surface oil at roughly 3 percent of its speed, and outside 2.5 to 11 m/s a dark patch on SAR stops being interpretable at all. Bearing is the direction it blows towards."
        />
        <Cell
          label="Sea temp"
          value={r.sstC !== null ? `${r.sstC.toFixed(1)} C` : "n/a"}
          title="Sea surface temperature. Warmer water weathers and evaporates oil faster, which is part of why the age band is a band."
        />
        <Cell
          label="Air temp"
          value={r.airTempC !== null ? `${r.airTempC.toFixed(1)} C` : "n/a"}
          title="2 m air temperature."
        />
      </div>

      {/* PLAN.md 16A: every layer that moves names its source. */}
      <div className="forcing-provenance" title={forcing.provenance.note}>
        {forcing.provenance.current_source}
      </div>
    </div>
  );
}

function Cell({
  label,
  value,
  bearing,
  swatch,
  title,
}: {
  label: string;
  value: string;
  bearing?: number | null;
  swatch?: "current" | "wind";
  title: string;
}) {
  return (
    <div className="forcing-cell" title={title}>
      <span className="forcing-label">
        {swatch && <span className={`forcing-swatch ${swatch}`} aria-hidden="true" />}
        {label}
      </span>
      <span className="mono forcing-value">{value}</span>
      {bearing !== undefined && bearing !== null && (
        <span className="forcing-bearing">
          {/* Rotated to match the map's arrows, so the readout and the
              chart cannot disagree about which way the water is going. */}
          <span
            className="forcing-arrow"
            style={{ transform: `rotate(${bearing}deg)` }}
            aria-hidden="true"
          >
            ↑
          </span>
          <span className="mono">towards {Math.round(bearing)}&deg;</span>
        </span>
      )}
    </div>
  );
}
