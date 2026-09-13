import Accordion from "./Accordion";
import { VERDICT_BLURBS, type DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
  onFocusVessel: (mmsi: string) => void;
}

function formatUtc(iso: string): string {
  return new Date(iso).toISOString().slice(11, 16);
}

// The answer, stated once, at the top of the panel. Everything below it
// is the working. A judge who reads only this box should still come away
// with what the system concluded and how strong the claim is, so the
// verdict chip and the leading vessel stay visible with the working
// collapsed.
//
// The verdict chip is the first thing in it, because the three classes
// are not degrees of the same answer. DARK_CONFIRMED in particular is a
// finding, not a weaker version of ATTRIBUTED: every competing system
// files "no broadcasting suspect" as no result. See PLAN.md section 12.
export default function VerdictCard({ bundle, onFocusVessel }: Props) {
  const verdict = bundle.verdict;
  const top = bundle.suspects[0];
  const radar = bundle.radar_crosscheck;

  const chip = verdict ? (
    <div className={`verdict-chip verdict-${verdict.verdict.toLowerCase()}`} title={verdict.reasoning}>
      {verdict.verdict.replace("_", " ")}
    </div>
  ) : null;

  if (verdict?.verdict === "DARK_CONFIRMED") {
    return (
      <div className="verdict-card">
        {chip}
        <Accordion title="The finding">
          <p className="verdict-line">{VERDICT_BLURBS.DARK_CONFIRMED}</p>
          <dl className="verdict-facts">
            <dt>Unmatched targets</dt>
            <dd className="mono">{verdict.unmatched_targets.join(", ") || "none"}</dd>
            <dt>Radar picture</dt>
            <dd className="mono">
              {radar ? `${radar.n_matched} of ${radar.n_targets} hulls matched to AIS` : "not run"}
            </dd>
          </dl>
          <p className="verdict-line">
            This is not an identification. An unmatched target may be a vessel below AIS carriage requirements, a
            fishing craft or a buoy, and Sentinel-1 misses small vessels at GRD resolution.
          </p>
        </Accordion>
      </div>
    );
  }

  if (!top) {
    return (
      <div className="verdict-card">
        {chip}
        <Accordion title="No ranked suspect">
          <p className="verdict-line">
            Every vessel in the window was eliminated. The elimination log records the rule that cleared each one.
          </p>
        </Accordion>
      </div>
    );
  }

  const vessel = bundle.vessels.find((v) => v.mmsi === top.mmsi);
  const runnerUp = bundle.suspects[1];
  const margin = runnerUp ? top.total - runnerUp.total : null;
  const gap = vessel?.dark_gaps[0];

  return (
    <div className="verdict-card">
      {chip}
      <Accordion title={`Rank 1 of ${bundle.suspects.length} survivors: ${top.mmsi}`}>
        {/* Clicking the working focuses the vessel, as the whole card did
            before it collapsed. Not on the header, which only toggles. */}
        <div className="verdict-focus" onClick={() => onFocusVessel(top.mmsi)}>
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
            {top.radar_support && (
              <>
                <dt>Radar support</dt>
                <dd
                  className="mono radar-support"
                  title="An unmatched ship target in the SAR scene fell inside this vessel's dead-reckoned dark envelope, over live origin field mass."
                >
                  {top.radar_support}
                </dd>
              </>
            )}
            <dt>Score margin</dt>
            <dd className="mono">{margin === null ? "no runner up" : `${margin.toFixed(2)} over rank 2`}</dd>
            <dt>Eliminated</dt>
            <dd className="mono">
              {bundle.eliminations.length} of {bundle.vessels.length} vessels, each with a logged reason
            </dd>
          </dl>
          {verdict && <p className="verdict-line">{verdict.reasoning}</p>}
          <p className="verdict-line">
            This is a ranking, not an identification. The origin field stays a probability over space and time and is
            never collapsed to a point.
          </p>
          {bundle.infrastructure?.flagged && (
            <p className="verdict-line infrastructure-flag">{bundle.infrastructure.statement}</p>
          )}
        </div>
      </Accordion>
    </div>
  );
}
