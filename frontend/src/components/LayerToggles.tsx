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
      {bundle.forecast_field && (
        <label
          title={`Forward forecast, n=${bundle.forecast_field.n_members}. Response planning only, never an input to the ranking.`}
        >
          <input type="checkbox" checked={toggles.forecast} onChange={() => toggle("forecast")} />
          Forecast field
        </label>
      )}
      <label>
        <input type="checkbox" checked={toggles.traffic} onChange={() => toggle("traffic")} />
        AIS traffic
      </label>
      <label
        title={
          bundle.radar_crosscheck
            ? `${bundle.radar_crosscheck.n_targets} ship target(s) in the SAR scene, ${bundle.radar_crosscheck.n_unmatched} with no AIS association at the acquisition instant.`
            : "No radar cross check was run for this case."
        }
      >
        <input type="checkbox" checked={toggles.radar} onChange={() => toggle("radar")} />
        Radar ship targets
      </label>
      {/* The swatch list that used to sit here named each mark without
          explaining it, which is fine for someone who built the pipeline
          and useless for a room seeing it once. MapLegend replaced it
          with a sentence per mark, keyed to the layers actually on. */}
      {/* PLAN.md section 16A: a provenance chip next to the animated
          layers, so what moves on screen is traceable to its source. */}
      {preview && (
        <div className="legend provenance">
          <div>
            SAR {preview.display_db_window[0]} to {preview.display_db_window[1]} dB
          </div>
          <div>
            field n={bundle.origin_field.n_members}, seed={bundle.origin_field.seed}
          </div>
          {bundle.origin_field.kernel && <div>kernel {bundle.origin_field.kernel}</div>}
        </div>
      )}
    </div>
  );
}
