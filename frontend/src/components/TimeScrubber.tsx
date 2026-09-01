interface Props {
  times: string[];
  timeIndex: number;
  playing: boolean;
  acquiredAt: string;
  onChangeIndex: (i: number) => void;
  onTogglePlay: () => void;
}

export default function TimeScrubber({
  times,
  timeIndex,
  playing,
  acquiredAt,
  onChangeIndex,
  onTogglePlay,
}: Props) {
  const current = times[timeIndex];
  const offset = relativeToAcquisition(current, acquiredAt);

  return (
    <div className="scrubber">
      <button
        className="scrubber-play"
        onClick={onTogglePlay}
        title={playing ? "Pause the sweep." : "Sweep through the origin window."}
        aria-label={playing ? "Pause" : "Play"}
      >
        {playing ? "❚❚" : "▶"}
      </button>
      <span className="scrubber-bound">{formatUtc(times[0])}</span>
      <div className="scrubber-track">
        <input
          className="scrubber-range"
          type="range"
          min={0}
          max={times.length - 1}
          step={1}
          value={timeIndex}
          onChange={(e) => onChangeIndex(Number(e.target.value))}
          aria-label="Time within the origin window"
        />
        <div className="scrubber-ticks" aria-hidden="true">
          {times.map((t, i) => (
            <span key={t} className={i === timeIndex ? "tick active" : "tick"} />
          ))}
        </div>
      </div>
      <span className="scrubber-bound">{formatUtc(times[times.length - 1])}</span>
      <div className="scrubber-readout">
        <span className="scrubber-current mono">{formatUtc(current)} UTC</span>
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

function relativeToAcquisition(iso: string, acquiredAt: string): string {
  const deltaMin = Math.round((new Date(iso).getTime() - new Date(acquiredAt).getTime()) / 60000);
  if (deltaMin === 0) return "at acquisition";
  const before = deltaMin < 0;
  const mins = Math.abs(deltaMin);
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  const span = h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
  return before ? `${span} before acquisition` : `${span} after acquisition`;
}
