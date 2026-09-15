import { ArrowLeft } from "lucide-react";
import Disclosure from "./Disclosure";
import FactorBars from "./FactorBars";
import Stat from "./Stat";
import { darkReachKm, rankOf, vesselRole } from "../lib/vessel";
import type { DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
  mmsi: string;
  timeMs: number;
  onClear: () => void;
}

// One vessel's whole story, shown when it is clicked on the map. It takes
// the whole panel while it is open, rather than stacking above the case,
// so there is one thing to read at a time and one obvious way back.
//
// The order here is the order the question gets asked in: who is it,
// what did it do, when was it not looking, and only then what the
// scoring made of that. The score comes last on purpose. Leading with a
// number invites the room to argue with the number instead of with the
// behaviour that produced it.
export default function VesselFocusCard({ bundle, mmsi, timeMs, onClear }: Props) {
  const vessel = bundle.vessels.find((v) => v.mmsi === mmsi);
  if (!vessel) return null;

  const role = vesselRole(vessel, bundle.culprit_mmsi);
  const rank = rankOf(bundle, mmsi);
  const score = bundle.suspects.find((s) => s.mmsi === mmsi);
  const acq = new Date(bundle.scene.acquired_at).getTime();

  const timing = bundle.vessel_timing?.[mmsi];
  const win = bundle.origin_window;

  const first = vessel.points[0];
  const last = vessel.points[vessel.points.length - 1];

  return (
    <section className={`focus-card role-${role}`}>
      <div className="focus-bar">
        <button className="back-button" onClick={onClear} title="Show every vessel again">
          <ArrowLeft size={16} strokeWidth={1.8} aria-hidden="true" />
          Back to the case
        </button>
        <span className={`pill status-${role}`}>
          {role === "eliminated" ? "Eliminated" : `Rank ${rank ?? "?"} of ${bundle.suspects.length}`}
        </span>
      </div>

      <div className="panel-hero focus-hero">
        <span className="stat-label">{vessel.vessel_type}</span>
        <span className="focus-mmsi mono">{vessel.mmsi}</span>
        {vessel.elimination && (
          <div className="focus-elimination">
            <span className="mono focus-rule">{vessel.elimination.rule}</span>
            <p>{vessel.elimination.reason}</p>
          </div>
        )}
        <div className="stat-row three">
          <Stat size="sm" label="Track" value={`${relHours(first.ts, acq)} to ${relHours(last.ts, acq)}`} />
          <Stat size="sm" label="Pings" value={vessel.points.length} />
          <Stat size="sm" label="Dark periods" value={vessel.dark_gaps.length} tone={vessel.dark_gaps.length ? "suspect" : "default"} />
        </div>
      </div>

      <section className="panel-section">
        <h3 className="section-title">When it was not broadcasting</h3>
        {vessel.dark_gaps.length > 0 ? (
          vessel.dark_gaps.map((g) => {
            const live = timeMs >= new Date(g.start).getTime() && timeMs <= new Date(g.end).getTime();
            return (
              <div key={g.start} className={`gap-card${live ? " live" : ""}`}>
                <div className="gap-top">
                  <span className="mono">
                    {relHours(g.start, acq)} to {relHours(g.end, acq)}
                  </span>
                  {live && <span className="pill dark-now">Dark now</span>}
                </div>
                <div className="stat-row">
                  <Stat size="lg" label="Silent" value={Math.round(g.duration_min)} unit="min" tone="suspect" />
                  {/* The number that explains the size of the ring on the
                      map, which otherwise reads as an arbitrary circle. */}
                  <Stat size="lg" label="Could reach" value={Math.round(darkReachKm(g))} unit="km" />
                </div>
                <Disclosure label="What the ring and the dashed line show">
                  <p>
                    Silent for {Math.round(g.duration_min)} minutes, so it could have travelled up to{" "}
                    {Math.round(darkReachKm(g))} km in any direction. The dashed line on the map assumes it held its
                    course; the shaded ring is everywhere else it could have gone.
                  </p>
                </Disclosure>
              </div>
            );
          })
        ) : (
          <p className="prose muted">
            Broadcast continuously through the window. Every position on the map for this vessel was reported, none
            reconstructed.
          </p>
        )}
      </section>

      {timing && timing.lag_hours !== null && (
        /* What F9 actually looked at for this vessel. The bar in the
           score block below is meaningless without it: it says a
           number, this says which hour produced the number and whether
           that hour was inside the window, inside the window's own
           uncertainty, or genuinely outside both. */
        <section className={`panel-section focus-timing timing-${timingState(timing)}`}>
          <h3 className="section-title">When it was over the origin</h3>
          <div className="timing-line">
            <Stat size="lg" label="Best opportunity" value={`-${timing.lag_hours.toFixed(1)}`} unit="h" />
            <span className={`pill timing-${timingState(timing)}`}>
              {timing.within_band
                ? "Inside the window"
                : timing.within_uncertainty
                  ? "Inside the margin"
                  : `${timing.offset_hours?.toFixed(1)} h beyond`}
            </span>
          </div>
          {win && (
            <p className="focus-timing-window mono">
              window {win.earliest_hours_before.toFixed(0)} to {win.latest_hours_before.toFixed(0)} h
              {win.band_uncertainty_hours != null && `, ±${win.band_uncertainty_hours.toFixed(0)} h uncertainty`}
            </p>
          )}
          <Disclosure label="How timing is scored">
            <p>{timing.statement}</p>
            {win?.timing_statement && <p className="muted">{win.timing_statement}</p>}
          </Disclosure>
        </section>
      )}

      {score && (
        <section className="panel-section">
          <h3 className="section-title">What the scoring made of it</h3>
          <Stat size="hero" label="Total score" value={score.total.toFixed(2)} tone={role === "culprit" ? "suspect" : "default"} />
          <FactorBars factors={score.factors} />
          {vessel.integrity_flags && vessel.integrity_flags.length > 0 && (
            <ul className="flag-list">
              {vessel.integrity_flags.map((flag, i) => (
                <li key={`${flag.kind}-${i}`}>
                  <span className="mono">{flag.kind}</span> {flag.detail}
                </li>
              ))}
            </ul>
          )}
          <Disclosure label="In plain words">
            <p>{score.narrative}</p>
          </Disclosure>
        </section>
      )}
    </section>
  );
}

// Three states, never two: inside the window, inside the margin the
// window's own edges are uncertain by, or actually outside both. Only
// the third one is penalised.
function timingState(t: { within_band: boolean | null; within_uncertainty: boolean | null }): string {
  if (t.within_band) return "inside";
  if (t.within_uncertainty) return "margin";
  return "outside";
}

function relHours(iso: string, acqMs: number): string {
  const h = (new Date(iso).getTime() - acqMs) / 3_600_000;
  const sign = h < 0 ? "-" : "+";
  const abs = Math.abs(h);
  return `${sign}${abs.toFixed(1)}h`;
}
