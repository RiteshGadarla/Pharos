import type { DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
  onFocusVessel: (mmsi: string) => void;
}

function formatUtc(iso: string): string {
  return new Date(iso).toISOString().slice(11, 16);
}

// The answer, stated once, at the top of the panel. Everything below it
// is the working. A judge who reads only this box should still come away
// with what the system concluded and how strong the claim is.
export default function VerdictCard({ bundle, onFocusVessel }: Props) {
  const top = bundle.suspects[0];
  if (!top) {
    return (
      <div className="verdict-card">
        <div className="verdict-label">NO RANKED SUSPECT</div>
        <p className="verdict-line">
          Every vessel in the window was eliminated. The elimination log records the rule that cleared each one.
        </p>
      </div>
    );
  }

  const vessel = bundle.vessels.find((v) => v.mmsi === top.mmsi);
  const runnerUp = bundle.suspects[1];
  const margin = runnerUp ? top.total - runnerUp.total : null;
  const gap = vessel?.dark_gaps[0];

  return (
    <div className="verdict-card" onClick={() => onFocusVessel(top.mmsi)}>
      <div className="verdict-label">RANK 1 OF {bundle.suspects.length} SURVIVORS</div>
      <div className="verdict-headline">
        <span className="mono verdict-mmsi">{top.mmsi}</span>
        <span className="verdict-type">{vessel?.vessel_type ?? "unknown type"}</span>
      </div>
      <dl className="verdict-facts">
        {gap && (
          <>
            <dt>Dark period</dt>
            <dd className="mono">
              {formatUtc(gap.start)} to {formatUtc(gap.end)} UTC, {Math.round(gap.duration_min)} min
            </dd>
          </>
        )}
        <dt>Score margin</dt>
        <dd className="mono">
          {margin === null ? "no runner up" : `${margin.toFixed(2)} over rank 2`}
        </dd>
        <dt>Eliminated</dt>
        <dd className="mono">
          {bundle.eliminations.length} of {bundle.vessels.length} vessels, each with a logged reason
        </dd>
      </dl>
      <p className="verdict-line">
        This is a ranking, not an identification. The origin field stays a probability over space and time and is
        never collapsed to a point.
      </p>
    </div>
  );
}
