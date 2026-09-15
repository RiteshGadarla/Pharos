import Accordion from "./Accordion";
import EvidencePanel from "./EvidencePanel";
import Stat from "./Stat";
import type { DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
}

// Stage 1's side panel: what the satellite saw, what survived the checks
// applied to it, and, one click down, the acquisition it came from.
//
// The slick leads because it is the claim. The scene facts that let a
// room trust it (one real acquisition with a time and a footprint, not a
// composite assembled to make the argument work) stay a click away with
// their provenance note intact.
export default function ScenePanel({ bundle }: Props) {
  const scene = bundle.scene;
  const primary = bundle.detections.find((d) => d.detection_id === bundle.primary_detection_id);
  const suppressed = bundle.detections.filter((d) => d.gate.verdict === "suppress").length;
  const f = bundle.slick_features;

  return (
    <>
      <section className="panel-hero">
        <span className="panel-kicker">Primary detection</span>
        <div className="stat-row">
          <Stat size="hero" label="Slick area" value={f.area_km2.toFixed(2)} unit="km²" tone="oil" />
          {primary && (
            <Stat
              size="lg"
              label="Detector confidence"
              value={primary.mean_class_prob.toFixed(2)}
              sub={`${bundle.detections.length} candidate${bundle.detections.length === 1 ? "" : "s"}, ${suppressed} suppressed`}
            />
          )}
        </div>
        <p className="panel-hero-sub mono">
          {scene.scene_id} · {formatUtc(scene.acquired_at)} UTC · {scene.sensor ?? "sentinel1"}
        </p>
      </section>

      <EvidencePanel bundle={bundle} />

      <div className="panel-accordions">
        <Accordion title="Slick measurements">
          <dl className="facts">
            <dt>Area</dt>
            <dd className="mono">{f.area_km2.toFixed(2)} km²</dd>
            <dt>Perimeter</dt>
            <dd className="mono">{f.perimeter_km.toFixed(2)} km</dd>
            <dt>Contrast</dt>
            <dd className="mono">{f.contrast_db.toFixed(1)} dB</dd>
            <dt>Complexity</dt>
            <dd className="mono">{f.complexity_ratio.toFixed(2)}</dd>
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
        </Accordion>

        <Accordion title="Acquisition">
          <dl className="facts">
            <dt>Scene</dt>
            <dd className="mono">{scene.scene_id}</dd>
            <dt>Acquired</dt>
            <dd className="mono">{formatUtc(scene.acquired_at)} UTC</dd>
            <dt>Sensor</dt>
            <dd className="mono">{scene.sensor ?? "sentinel1"}</dd>
            <dt>CRS</dt>
            <dd className="mono">{scene.crs}</dd>
            <dt>Footprint</dt>
            <dd className="mono wrap">{formatBbox(scene.bbox)}</dd>
          </dl>
          <p className="prose muted">{scene.note}</p>
        </Accordion>

        <Accordion title={`Candidates (${bundle.detections.length})`}>
          <dl className="facts">
            <dt>Polygons</dt>
            <dd className="mono">{bundle.detections.length}</dd>
            <dt>Suppressed</dt>
            <dd className="mono">{suppressed}</dd>
            <dt>Primary</dt>
            <dd className="mono wrap">{primary?.detection_id ?? "none"}</dd>
          </dl>
          {/* A suppressed detection is marked, never deleted. Saying so
              here is the difference between a filter and a disappearance. */}
          <p className="prose muted">
            Suppressed polygons stay on the map in grey with their reason on hover. Nothing the detector found is
            removed from the record.
          </p>
        </Accordion>
      </div>
    </>
  );
}

function formatUtc(iso: string): string {
  return new Date(iso).toISOString().slice(0, 16).replace("T", " ");
}

function formatBbox(bbox: [number, number, number, number]): string {
  return bbox.map((v) => v.toFixed(3)).join(", ");
}
