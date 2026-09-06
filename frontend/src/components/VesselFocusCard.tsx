import { darkReachKm, rankOf, vesselRole } from "../lib/vessel";
import { FACTOR_LABELS, type DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
  mmsi: string;
  timeMs: number;
  onClear: () => void;
}

// One vessel's whole story, shown when it is clicked on the map.
//
// Clicking a track used to do almost nothing visible: it changed a
// highlight colour. The map is where a viewer forms a question about a
// specific vessel ("what is that one doing?") and until now the only
// place with an answer was a ranked list that did not obviously
// correspond to anything on screen.
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
      <div className="focus-head">
        <div>
          <span className="focus-mmsi mono">{vessel.mmsi}</span>
          <span className="focus-type">{vessel.vessel_type}</span>
        </div>
        <button className="focus-clear" onClick={onClear} title="Show every vessel again">
          Clear
        </button>
      </div>

      <div className={`focus-status status-${role}`}>
        {role === "eliminated"
          ? "Eliminated"
          : role === "culprit"
            ? `Rank ${rank ?? "?"} of ${bundle.suspects.length} survivors`
            : `Rank ${rank ?? "?"} of ${bundle.suspects.length} survivors`}
      </div>

      {vessel.elimination && (
        <p className="focus-reason">
          {vessel.elimination.reason}
          <span className="focus-rule mono">{vessel.elimination.rule}</span>
        </p>
      )}

      <dl className="evidence-facts">
        <dt>Track</dt>
        <dd className="mono">
          {relHours(first.ts, acq)} to {relHours(last.ts, acq)}
        </dd>
        <dt>Pings</dt>
        <dd className="mono">{vessel.points.length}</dd>
      </dl>

      {vessel.dark_gaps.length > 0 ? (
        <div className="focus-dark">
          <h3 className="focus-sub">Dark periods</h3>
          {vessel.dark_gaps.map((g) => {
            const live = timeMs >= new Date(g.start).getTime() && timeMs <= new Date(g.end).getTime();
            return (
              <div key={g.start} className={`focus-gap ${live ? "live" : ""}`}>
                <div className="focus-gap-line">
                  <span className="mono">
                    {relHours(g.start, acq)} to {relHours(g.end, acq)}
                  </span>
                  <span className="mono focus-gap-dur">{Math.round(g.duration_min)} min</span>
                  {live && <span className="focus-gap-now">DARK NOW</span>}
                </div>
                {/* The number that explains the size of the ring on the
                    map, which otherwise reads as an arbitrary circle. */}
                <p className="focus-gap-note">
                  Silent for {Math.round(g.duration_min)} minutes, so it could have travelled up to{" "}
                  {Math.round(darkReachKm(g))} km in any direction. The dashed line on the map assumes it
                  held its course; the shaded ring is everywhere else it could have gone.
                </p>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="focus-gap-note muted">
          Broadcast continuously through the window. Every position on the map for this vessel was reported,
          none reconstructed.
        </p>
      )}

      {timing && timing.lag_hours !== null && (
        /* What F9 actually looked at for this vessel. The bar in the
           score block below is meaningless without it: it says a
           number, this says which hour produced the number and whether
           that hour was inside the window, inside the window's own
           uncertainty, or genuinely outside both. */
        <div className={`focus-timing timing-${timingState(timing)}`}>
          <h3 className="focus-sub">When it was over the origin</h3>
          <div className="focus-timing-line">
            <span className="mono focus-timing-lag">-{timing.lag_hours.toFixed(1)}h</span>
            <span className={`timing-pill timing-${timingState(timing)}`}>
              {timing.within_band
                ? "INSIDE THE WINDOW"
                : timing.within_uncertainty
                  ? "INSIDE THE MARGIN"
                  : `${timing.offset_hours?.toFixed(1)}h BEYOND`}
            </span>
          </div>
          {win && (
            <p className="focus-timing-window mono muted">
              window {win.earliest_hours_before.toFixed(0)} to {win.latest_hours_before.toFixed(0)} h
              {win.band_uncertainty_hours != null &&
                `, +/-${win.band_uncertainty_hours.toFixed(0)} h uncertainty`}
            </p>
          )}
          <p className="focus-gap-note">{timing.statement}</p>
        </div>
      )}

      {score && (
        <div className="focus-score">
          <h3 className="focus-sub">Why it scores what it does</h3>
          {Object.entries(score.factors)
            .sort((a, b) => b[1] - a[1])
            .map(([name, value]) => (
              <div className="focus-factor" key={name}>
                <span className="focus-factor-label">{FACTOR_LABELS[name] ?? name}</span>
                <span className={`mono focus-factor-value ${value < 0 ? "negative" : ""}`}>
                  {value >= 0 ? "+" : ""}
                  {value.toFixed(3)}
                </span>
              </div>
            ))}
          <p className="focus-narrative">{score.narrative}</p>
        </div>
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
