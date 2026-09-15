import { ArrowRight } from "lucide-react";
import Disclosure from "./Disclosure";
import Stat from "./Stat";
import { VERDICT_BLURBS, type DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
  onFocusVessel: (mmsi: string) => void;
}

function formatUtc(iso: string): string {
  return new Date(iso).toISOString().slice(11, 16);
}

function darkSub(gaps: { start: string; end: string }[]): string {
  if (gaps.length === 0) return "broadcast throughout";
  if (gaps.length === 1) return `${formatUtc(gaps[0].start)} to ${formatUtc(gaps[0].end)} UTC`;
  return `${gaps.length} periods`;
}

// The answer, stated once, at the top of the panel. Everything below it
// is the working. A judge who reads only this box should still come away
// with what the system concluded and how strong the claim is, so the
// verdict chip, the leading vessel and its margin are the largest things
// in it and the reasoning sits one click down.
//
// The verdict chip is the first thing in it, because the three classes
// are not degrees of the same answer. DARK_CONFIRMED in particular is a
// finding, not a weaker version of ATTRIBUTED: every competing system
// files "no broadcasting suspect" as no result. See PLAN.md section 12.
export default function VerdictCard({ bundle, onFocusVessel }: Props) {
  const verdict = bundle.verdict;
  const top = bundle.suspects[0];
  const radar = bundle.radar_crosscheck;

  const head = verdict ? (
    <div className="verdict-top">
      <span className={`verdict-chip large verdict-${verdict.verdict.toLowerCase()}`}>
        {verdict.verdict.replace("_", " ")}
      </span>
      <span className="verdict-blurb">{VERDICT_BLURBS[verdict.verdict]}</span>
    </div>
  ) : null;

  const infrastructure = bundle.infrastructure?.flagged ? (
    <p className="verdict-warn">{bundle.infrastructure.statement}</p>
  ) : null;

  if (verdict?.verdict === "DARK_CONFIRMED") {
    const unmatched = verdict.unmatched_targets;
    return (
      <section className="verdict-card panel-hero">
        {head}
        <span className="stat-label">Unmatched radar target{unmatched.length === 1 ? "" : "s"} in the origin field</span>
        <div className="verdict-lead static">
          <span className="verdict-mmsi mono tone-radar">{unmatched.join(", ") || "none"}</span>
        </div>
        <div className="stat-row">
          <Stat
            label="Hulls matched to AIS"
            value={radar ? `${radar.n_matched}/${radar.n_targets}` : "n/a"}
            sub={radar ? "radar saw the rest, AIS did not" : "cross check not run"}
          />
          <Stat label="Eliminated" value={`${bundle.eliminations.length}/${bundle.vessels.length}`} sub="broadcasting vessels" />
        </div>
        {infrastructure}
        <Disclosure label="What this finding means">
          <p>{verdict.reasoning}</p>
          <p>
            This is not an identification. An unmatched target may be a vessel below AIS carriage requirements, a
            fishing craft or a buoy, and Sentinel-1 misses small vessels at GRD resolution.
          </p>
        </Disclosure>
      </section>
    );
  }

  if (!top) {
    return (
      <section className="verdict-card panel-hero">
        {head}
        <span className="stat-label">No ranked suspect</span>
        <div className="stat-row">
          <Stat label="Eliminated" value={`${bundle.eliminations.length}/${bundle.vessels.length}`} sub="each with a logged rule" />
        </div>
        {infrastructure}
        <Disclosure label="Why there is no ranking">
          <p>Every vessel in the window was eliminated. The elimination log records the rule that cleared each one.</p>
          {verdict && <p>{verdict.reasoning}</p>}
        </Disclosure>
      </section>
    );
  }

  const vessel = bundle.vessels.find((v) => v.mmsi === top.mmsi);
  const runnerUp = bundle.suspects[1];
  const margin = runnerUp ? top.total - runnerUp.total : null;
  const darkMin = vessel ? vessel.dark_gaps.reduce((sum, g) => sum + g.duration_min, 0) : 0;

  return (
    <section className="verdict-card panel-hero">
      {head}
      <span className="stat-label">
        Rank 1 of {bundle.suspects.length} survivor{bundle.suspects.length === 1 ? "" : "s"}
      </span>
      <button className="verdict-lead" onClick={() => onFocusVessel(top.mmsi)} title="Follow this vessel on the map">
        <span className="verdict-mmsi mono">{top.mmsi}</span>
        <span className="verdict-type">{vessel?.vessel_type ?? "unknown type"}</span>
        <ArrowRight className="verdict-lead-arrow" size={20} strokeWidth={1.8} aria-hidden="true" />
      </button>
      <div className="stat-row three">
        <Stat
          label="Lead over #2"
          value={margin === null ? "sole" : `+${margin.toFixed(2)}`}
          sub={`score ${top.total.toFixed(2)}`}
        />
        <Stat
          label="Dark"
          value={darkMin > 0 ? Math.round(darkMin) : "none"}
          unit={darkMin > 0 ? "min" : undefined}
          tone={darkMin > 0 ? "suspect" : "default"}
          sub={darkSub(vessel?.dark_gaps ?? [])}
        />
        <Stat label="Eliminated" value={`${bundle.eliminations.length}/${bundle.vessels.length}`} sub="with reasons" />
      </div>
      {top.radar_support && (
        <p
          className="verdict-radar mono"
          title="An unmatched ship target in the SAR scene fell inside this vessel's dead-reckoned dark envelope, over live origin field mass."
        >
          Radar support: {top.radar_support}
        </p>
      )}
      {infrastructure}
      <Disclosure label={`Why ${verdict ? verdict.verdict.replace("_", " ").toLowerCase() : "this ranking"}`}>
        {verdict && <p>{verdict.reasoning}</p>}
        <p>
          This is a ranking, not an identification. The origin field stays a probability over space and time and is
          never collapsed to a point.
        </p>
      </Disclosure>
    </section>
  );
}
