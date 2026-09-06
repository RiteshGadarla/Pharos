import { acquisitionFraction, fractionAtMs, originWindowFraction, type Timeline, type TimelineFrame } from "../lib/timeline";
import type { OriginWindowJSON } from "../types";

interface Props {
  timeline: Timeline;
  // The window this stage allows. Stage 2 spans the whole axis, stage 3
  // is confined to the backward half: the attribution reads the origin
  // field, so letting the scrubber run into the forecast there would
  // show a ranking against a field that produced none of it.
  range: [number, number];
  frameIndex: number;
  playing: boolean;
  acquiredAt: string;
  // The age-implied origin window, drawn as a band on the axis. The
  // hours the slick's own condition says the discharge plausibly
  // happened in, and the hours F1 and F2 weight most heavily.
  originWindow?: OriginWindowJSON;
  // The focused vessel's best opportunity to be the source, drawn as a
  // caret against the band. This is the whole of F9 made visible: the
  // band is the claim about when, the caret is when this vessel was
  // actually there, and the gap between them is what gets scored.
  opportunity?: { mmsi: string; lagHours: number; state: string } | null;
  spreadKm: number;
  onChangeIndex: (i: number) => void;
  onTogglePlay: () => void;
}

export default function TimeScrubber({
  timeline,
  range,
  frameIndex,
  playing,
  acquiredAt,
  originWindow,
  opportunity,
  spreadKm,
  onChangeIndex,
  onTogglePlay,
}: Props) {
  const frames = timeline.frames;
  const current = frames[frameIndex];
  const offset = relativeToAcquisition(current, acquiredAt, timeline.stepMs);
  // Where the acquisition instant sits along the visible track. null
  // when it falls outside this stage's window.
  const acquiredMs = new Date(acquiredAt).getTime();
  const acquiredFraction = acquisitionFraction(timeline, range, acquiredMs);
  const spansForward = range[1] > timeline.pivot;
  const windowBand = originWindow
    ? originWindowFraction(
        timeline, range, acquiredMs,
        originWindow.earliest_hours_before,
        originWindow.latest_hours_before,
      )
    : null;
  // A single instant, so it goes through fractionAtMs rather than the
  // window mapper: originWindowFraction returns null on a zero-width
  // span (hi <= lo), which is right for a band and useless for a mark.
  const opportunityAt =
    opportunity != null
      ? fractionAtMs(timeline, range, acquiredMs - opportunity.lagHours * 3_600_000)
      : null;

  return (
    <div className="scrubber">
      <button
        className="scrubber-play"
        onClick={onTogglePlay}
        title={playing ? "Pause the rewind." : "Rewind backwards from the acquisition time."}
        aria-label={playing ? "Pause" : "Rewind"}
      >
        {playing ? "❚❚" : "◀◀"}
      </button>
      <span className="scrubber-bound">{formatUtc(frames[range[0]].iso)}</span>
      <div className="scrubber-track">
        <input
          className="scrubber-range"
          type="range"
          min={range[0]}
          max={range[1]}
          step={1}
          value={frameIndex}
          onChange={(e) => onChangeIndex(Number(e.target.value))}
          aria-label={spansForward ? "Time across the origin window and the forecast" : "Time within the origin window"}
        />
        {/* Behind the ticks: the hours the slick's condition says the
            discharge plausibly happened in. It is shaded rather than
            bounded by hard edges because the weighting tapers, and it
            never covers the whole axis because a band that explained
            everything would be explaining nothing. */}
        {windowBand && (
          <div
            className="scrubber-window"
            style={{ left: `${windowBand[0] * 100}%`, width: `${(windowBand[1] - windowBand[0]) * 100}%` }}
            title={originWindow?.statement}
          >
            <span className="scrubber-window-label">
              {originWindow?.age_band?.toUpperCase()} ORIGIN WINDOW
            </span>
          </div>
        )}
        {opportunity && opportunityAt !== null && (
          <div
            className={`scrubber-opportunity timing-${opportunity.state}`}
            style={{ left: `${opportunityAt * 100}%` }}
            title={`${opportunity.mmsi} was over the origin area at -${opportunity.lagHours.toFixed(1)} h`}
          >
            <span className="scrubber-opportunity-caret" />
            <span className="scrubber-opportunity-label mono">{opportunity.mmsi}</span>
          </div>
        )}
        <div className="scrubber-ticks" aria-hidden="true">
          {frames.slice(range[0], range[1] + 1).map((f, i) => (
            <span
              key={f.iso + f.direction}
              className={`tick ${f.direction} ${i + range[0] === frameIndex ? "active" : ""}`}
            />
          ))}
        </div>
        {/* The acquisition instant is the one fixed point on this axis:
            everything left of it is reconstructed, everything right of
            it is predicted, and only the instant itself was observed. */}
        {spansForward && acquiredFraction !== null && (
          <div className="scrubber-pivot" style={{ left: `${acquiredFraction * 100}%` }} aria-hidden="true">
            <span className="scrubber-pivot-label">ACQUIRED</span>
          </div>
        )}
      </div>
      <span className="scrubber-bound">{formatUtc(frames[range[1]].iso)}</span>

      <div
        className={`scrubber-direction ${current.direction}`}
        title={
          current.direction === "backward"
            ? "The backward origin field: where the slick could have come from. This is what the ranking reads."
            : "The forward forecast: where the slick goes next. Never an input to the ranking."
        }
      >
        {current.direction === "backward" ? "ORIGIN" : "FORECAST"}
      </div>

      {/* The colour ramp is normalised per timestep so the field's shape
          stays readable as it spreads, which means the eye cannot judge
          how much certainty was lost. This says it as a number. */}
      <div
        className="scrubber-spread"
        title="Mass-weighted spread of the field at this instant. It grows as the hindcast runs backwards and knowledge runs out."
      >
        <span className="scrubber-spread-label">SPREAD</span>
        <span className="mono scrubber-spread-value">{spreadKm.toFixed(1)} km</span>
      </div>
      <div className="scrubber-readout">
        <span className="scrubber-current mono">{formatUtc(current.iso)} UTC</span>
        {/* The absolute time alone does not tell a room how far back
            from the satellite pass they are looking. */}
        <span className="scrubber-offset">{offset}</span>
      </div>
    </div>
  );
}

function formatUtc(iso: string): string {
  return new Date(iso).toISOString().slice(0, 16).replace("T", " ");
}

function relativeToAcquisition(frame: TimelineFrame, acquiredAt: string, stepMs: number): string {
  const deltaMs = frame.ms - new Date(acquiredAt).getTime();
  // Anything inside the bin holding the acquisition instant reads as
  // "at acquisition". The bin's centre can sit up to half a step from
  // the satellite pass, and printing that half step as a real offset
  // would claim a time resolution the field does not have.
  if (Math.abs(deltaMs) <= stepMs / 2) return "at acquisition";
  const deltaMin = Math.round(deltaMs / 60000);
  const before = deltaMin < 0;
  const mins = Math.abs(deltaMin);
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  const span = h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
  return before ? `${span} before acquisition` : `${span} after acquisition`;
}
