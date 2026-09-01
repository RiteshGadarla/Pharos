import type { DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
}

const GATE_COPY: Record<string, string> = {
  accept: "accepted",
  downgrade: "downgraded",
  suppress: "suppressed",
};

// The two questions a room asks before it will accept any of the
// attribution: how do you know that dark patch is oil and not a
// look-alike, and how old is it. Both answers live in the dossier
// already; this puts them on the screen, with their reasoning, so they
// do not have to be recited from memory.
export default function EvidencePanel({ bundle }: Props) {
  const primary = bundle.detections.find((d) => d.detection_id === bundle.primary_detection_id);
  const f = bundle.slick_features;

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

      <div className="evidence-row">
        <div className="evidence-line">
          <span className="evidence-key">Age band</span>
          <span className="mono">{f.age_band}</span>
        </div>
        <p className="evidence-reason">{f.age_reasoning}</p>
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
