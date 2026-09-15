import Disclosure from "./Disclosure";
import type { DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
}

const GATE_COPY: Record<string, string> = {
  accept: "accepted",
  downgrade: "downgraded",
  suppress: "suppressed",
};

const OPTICAL_COPY: Record<string, string> = {
  agree: "Optical agrees",
  disagree: "Optical disagrees",
  no_coverage: "No coverage",
};

// The questions a room asks before it will accept any of the
// attribution: how do you know that dark patch is oil and not a
// look-alike, how old is it, and did anything other than radar see it.
// All three answers live in the dossier already; this puts them on the
// screen as three checks, each with its result up front and its
// reasoning one click below.
//
// The optical row states no_coverage as plainly as it states agreement,
// because no_coverage is the common case and is not a weakness: SAR is
// the primary sensor precisely because it images through cloud, at
// night and in any weather.
export default function EvidencePanel({ bundle }: Props) {
  const primary = bundle.detections.find((d) => d.detection_id === bundle.primary_detection_id);
  const f = bundle.slick_features;
  const win = bundle.origin_window;

  return (
    <section className="panel-section">
      <h3 className="section-title">Checks on the detection</h3>
      <div className="checks">
        {primary && (
          <div className="check">
            <div className="check-head">
              <span className="check-label">Wind gate</span>
              <span className={`pill gate-${primary.gate.verdict}`}>
                {GATE_COPY[primary.gate.verdict] ?? primary.gate.verdict}
              </span>
            </div>
            <div className="check-value mono">
              {primary.gate.wind_speed_ms.toFixed(1)}
              <span className="check-unit">m/s at the slick</span>
            </div>
            <Disclosure label={`Why ${GATE_COPY[primary.gate.verdict] ?? primary.gate.verdict}`}>
              <p>{primary.gate.reason}</p>
            </Disclosure>
          </div>
        )}

        {/* The estimated age, stated where the slick is detected rather
            than three stages later. It is a RANGE, never a number of
            hours: PLAN.md's non-goals rule out absolute slick age from a
            single SAR acquisition, and a single figure here would claim
            exactly the precision the caveat below denies. */}
        <div className="check">
          <div className="check-head">
            <span className="check-label">Estimated age</span>
            <span className={`pill age-${f.age_band}`}>{f.age_band}</span>
          </div>
          <div className="check-value mono">
            {win ? `${win.earliest_hours_before.toFixed(0)} to ${win.latest_hours_before.toFixed(0)}` : f.age_band}
            {win && <span className="check-unit">h before acquisition</span>}
          </div>
          <Disclosure label="How the age is bounded">
            <p>{f.age_reasoning}</p>
            {win && win.band_uncertainty_hours != null && (
              /* Said out loud, because the alternative is a reader taking
                 the range for a hard boundary. */
              <p>
                The edges carry about {win.band_uncertainty_hours.toFixed(0)} h of uncertainty of their own. A vessel
                that passed within that margin of the range is scored as though it were inside it.
              </p>
            )}
            <p className="muted">
              Absolute age in hours cannot be estimated from a single SAR acquisition, so this system reports a band and
              its reasoning instead.
            </p>
          </Disclosure>
        </div>

        {bundle.optical && (
          <div className="check">
            <div className="check-head">
              <span className="check-label">Optical corroboration</span>
              <span className={`pill optical-${bundle.optical.status}`}>
                {OPTICAL_COPY[bundle.optical.status] ?? bundle.optical.status}
              </span>
            </div>
            {bundle.optical.sensor && <div className="check-value mono">{bundle.optical.sensor}</div>}
            <Disclosure label="What this means">
              <p>{bundle.optical.reasoning}</p>
            </Disclosure>
          </div>
        )}
      </div>
    </section>
  );
}
