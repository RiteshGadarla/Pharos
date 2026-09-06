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
  agree: "OPTICAL AGREES",
  disagree: "OPTICAL DISAGREES",
  no_coverage: "NO OPTICAL COVERAGE",
};

// The questions a room asks before it will accept any of the
// attribution: how do you know that dark patch is oil and not a
// look-alike, how old is it, and did anything other than radar see it.
// All three answers live in the dossier already; this puts them on the
// screen, with their reasoning, so they do not have to be recited from
// memory.
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
    <section className="evidence-panel">
      <h2 className="evidence-heading">Scene evidence</h2>

      {primary && (
        <div className="evidence-row">
          <div className="evidence-line">
            <span className={`gate-pill gate-${primary.gate.verdict}`}>
              WIND GATE {GATE_COPY[primary.gate.verdict]?.toUpperCase() ?? primary.gate.verdict.toUpperCase()}
            </span>
            <span className="mono muted">{primary.gate.wind_speed_ms.toFixed(1)} m/s</span>
          </div>
          <p className="evidence-reason">{primary.gate.reason}</p>
        </div>
      )}

      {bundle.optical && (
        <div className="evidence-row">
          <div className="evidence-line">
            <span className={`gate-pill optical-${bundle.optical.status}`}>
              {OPTICAL_COPY[bundle.optical.status] ?? bundle.optical.status.toUpperCase()}
            </span>
            {bundle.optical.sensor && <span className="mono muted">{bundle.optical.sensor}</span>}
          </div>
          <p className="evidence-reason">{bundle.optical.reasoning}</p>
        </div>
      )}

      {/* The estimated age, stated where the slick is detected rather
          than three stages later. It is a RANGE, never a number of
          hours: PLAN.md's non-goals rule out absolute slick age from a
          single SAR acquisition, and a single figure here would claim
          exactly the precision the caveat below denies. */}
      <div className="evidence-row">
        <div className="evidence-line">
          <span className="evidence-key">Estimated age</span>
          <span className="mono age-estimate">
            {win
              ? `${win.earliest_hours_before.toFixed(0)} to ${win.latest_hours_before.toFixed(0)} h`
              : f.age_band}
          </span>
          <span className={`age-pill age-${f.age_band}`}>{f.age_band.toUpperCase()}</span>
        </div>
        <p className="evidence-reason">{f.age_reasoning}</p>
        {win && win.band_uncertainty_hours != null && (
          /* Said out loud, because the alternative is a reader taking
             the range for a hard boundary. If the discharge really
             happened at -14 h against an 0 to 12 h band, the vessels
             that passed in those extra hours are still candidates, and
             the scoring treats them as such. */
          <p className="evidence-reason">
            The edges carry about {win.band_uncertainty_hours.toFixed(0)} h of uncertainty of their own. A vessel
            that passed within that margin of the range is scored as though it were inside it.
          </p>
        )}
        <p className="evidence-reason muted">
          Absolute age in hours cannot be estimated from a single SAR acquisition, so this system reports a band and
          its reasoning instead.
        </p>
      </div>

      <dl className="evidence-facts">
        <dt>Area</dt>
        <dd className="mono">{f.area_km2.toFixed(2)} km²</dd>
        <dt>Contrast</dt>
        <dd className="mono">{f.contrast_db.toFixed(1)} dB</dd>
        <dt>Elongation</dt>
        <dd className="mono">{f.elongation.toFixed(2)}</dd>
        <dt>Major axis</dt>
        <dd className="mono">{f.major_axis_deg.toFixed(0)}°</dd>
        {primary && (
          <>
            <dt>Confidence</dt>
            <dd className="mono">{primary.mean_class_prob.toFixed(3)}</dd>
          </>
        )}
      </dl>
    </section>
  );
}
