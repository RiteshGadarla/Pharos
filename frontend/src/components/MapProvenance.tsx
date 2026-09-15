import type { LayerToggles } from "./MapView";
import type { DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
  toggles: LayerToggles;
}

// PLAN.md section 16A: every animated layer names its source on screen.
// A provenance chip is what turns moving pixels into evidence, so it
// stays visible rather than living inside the layer menu, and it sits
// where a chart carries its attribution: small, in the corner, keyed to
// the layers actually drawn.
export default function MapProvenance({ bundle, toggles }: Props) {
  const parts: string[] = [];
  const preview = bundle.scene.preview;
  if (toggles.scene && preview) {
    parts.push(`SAR ${preview.display_db_window[0]} to ${preview.display_db_window[1]} dB`);
  }
  if (toggles.field) {
    const f = bundle.origin_field;
    parts.push(`origin ${f.kernel ?? "drift"} n=${f.n_members} seed=${f.seed}`);
  }
  if (toggles.forecast && bundle.forecast_field) {
    parts.push(`forecast n=${bundle.forecast_field.n_members}`);
  }
  if (bundle.forcing && (toggles.current || toggles.wind)) {
    const p = bundle.forcing.provenance;
    // One line per source, so a long caveat ("synthetic fixture, not
    // real ...") stays whole rather than wrapping mid-phrase.
    if (p.current_source === p.wind_source) parts.push(`forcing: ${p.current_source}`);
    else {
      if (toggles.current) parts.push(`current: ${p.current_source}`);
      if (toggles.wind) parts.push(`wind: ${p.wind_source}`);
    }
  }
  if (parts.length === 0) return null;

  return (
    <div className="map-provenance mono" title={bundle.origin_field.forcing_source}>
      {parts.map((p) => (
        <span key={p}>{p}</span>
      ))}
    </div>
  );
}
