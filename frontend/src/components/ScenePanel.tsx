import EvidencePanel from "./EvidencePanel";
import type { DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
}

// Stage 1's side panel: what the satellite is, when it looked, and what
// survived the checks applied to what it saw.
//
// The scene facts sit above the evidence rows on purpose. Before a room
// will accept anything about drift or vessels it wants to know that the
// image is one real acquisition with a time and a footprint, not a
// composite assembled to make the argument work.
export default function ScenePanel({ bundle }: Props) {
  const scene = bundle.scene;
  const primary = bundle.detections.find((d) => d.detection_id === bundle.primary_detection_id);
  const suppressed = bundle.detections.filter((d) => d.gate.verdict === "suppress").length;

  return (
    <>
      <section className="stage-panel">
        <h2 className="evidence-heading">Acquisition</h2>
        <dl className="evidence-facts">
          <dt>Scene</dt>
          <dd className="mono">{scene.scene_id}</dd>
          <dt>Acquired</dt>
          <dd className="mono">{formatUtc(scene.acquired_at)} UTC</dd>
          <dt>Sensor</dt>
          <dd className="mono">{scene.sensor ?? "sentinel1"}</dd>
          <dt>CRS</dt>
          <dd className="mono">{scene.crs}</dd>
          <dt>Footprint</dt>
          <dd className="mono">{formatBbox(scene.bbox)}</dd>
        </dl>
        <p className="evidence-reason muted">{scene.note}</p>
      </section>

      <section className="stage-panel">
        <h2 className="evidence-heading">Candidates</h2>
        <dl className="evidence-facts">
          <dt>Polygons</dt>
          <dd className="mono">{bundle.detections.length}</dd>
          <dt>Suppressed</dt>
          <dd className="mono">{suppressed}</dd>
          <dt>Primary</dt>
          <dd className="mono">{primary?.detection_id ?? "none"}</dd>
        </dl>
        {/* A suppressed detection is marked, never deleted. Saying so
            here is the difference between a filter and a disappearance. */}
        <p className="evidence-reason muted">
          Suppressed polygons stay on the map in grey with their reason on hover. Nothing the detector found is
          removed from the record.
        </p>
      </section>

      <EvidencePanel bundle={bundle} />
    </>
  );
}

function formatUtc(iso: string): string {
  return new Date(iso).toISOString().slice(0, 16).replace("T", " ");
}

function formatBbox(bbox: [number, number, number, number]): string {
  return bbox.map((v) => v.toFixed(3)).join(", ");
}
