import type { LayerToggles as Toggles } from "./MapView";
import type { DemoBundle } from "../types";

interface Props {
  toggles: Toggles;
  onChange: (t: Toggles) => void;
  bundle: DemoBundle;
}

export default function LayerToggles({ toggles, onChange, bundle }: Props) {
  const toggle = (key: keyof Toggles) => onChange({ ...toggles, [key]: !toggles[key] });
  const preview = bundle.scene.preview;

  return (
    <div className="layer-toggles">
      <label title={preview?.note}>
        <input type="checkbox" checked={toggles.scene} onChange={() => toggle("scene")} />
        SAR scene
      </label>
      <label>
        <input type="checkbox" checked={toggles.detections} onChange={() => toggle("detections")} />
        Scene detections
      </label>
      <label title={`Backward drift ensemble, n=${bundle.origin_field.n_members}, seed=${bundle.origin_field.seed}.`}>
        <input type="checkbox" checked={toggles.field} onChange={() => toggle("field")} />
        Origin field
      </label>
      <label>
        <input type="checkbox" checked={toggles.traffic} onChange={() => toggle("traffic")} />
        AIS traffic
      </label>
      <div className="legend">
        <div className="legend-row">
          <span className="swatch swatch-oil" /> oil / origin field
        </div>
        <div className="legend-row">
          <span className="swatch swatch-suspect" /> rank 1 suspect
        </div>
        <div className="legend-row">
          <span className="swatch swatch-muted" /> other survivor
        </div>
        <div className="legend-row">
          <span className="swatch swatch-cleared" /> eliminated
        </div>
        <div className="legend-row">
          <span className="swatch swatch-dashed" /> dark period + reachable envelope
        </div>
      </div>
      {/* PLAN.md section 12A: a provenance chip next to the animated
          layers, so what moves on screen is traceable to its source. */}
      {preview && (
        <div className="legend provenance">
          <div>
            SAR {preview.display_db_window[0]} to {preview.display_db_window[1]} dB
          </div>
          <div>
            field n={bundle.origin_field.n_members}, seed={bundle.origin_field.seed}
          </div>
        </div>
      )}
    </div>
  );
}
