import { useEffect, useRef, useState } from "react";
import { Layers } from "lucide-react";
import type { LayerToggles as Toggles } from "./MapView";
import type { DemoBundle } from "../types";

interface Props {
  toggles: Toggles;
  onChange: (t: Toggles) => void;
  bundle: DemoBundle;
}

interface Row {
  key: keyof Toggles;
  label: string;
  swatch: string;
  title?: string;
}

// Every layer on the map, one click behind a single button.
//
// A stage sets the layers and never locks them (PLAN.md section 16), so
// every toggle stays live in every stage. They sit behind a button
// rather than floating open because during the demo the stage has
// already chosen them, and a permanently open checklist is chrome the
// room reads before it reads the map.
export default function LayerToggles({ toggles, onChange, bundle }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const toggle = (key: keyof Toggles) => onChange({ ...toggles, [key]: !toggles[key] });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const rows: Row[] = [
    { key: "scene", label: "SAR scene", swatch: "scene", title: bundle.scene.preview?.note },
    { key: "detections", label: "Scene detections", swatch: "oil" },
    {
      key: "field",
      label: "Origin field",
      swatch: "oil-field",
      title: `Backward drift ensemble, n=${bundle.origin_field.n_members}, seed=${bundle.origin_field.seed}.`,
    },
  ];
  if (bundle.forecast_field) {
    rows.push({
      key: "forecast",
      label: "Forecast field",
      swatch: "forecast",
      title: `Forward forecast, n=${bundle.forecast_field.n_members}. Response planning only, never an input to the ranking.`,
    });
  }
  rows.push(
    { key: "traffic", label: "AIS traffic", swatch: "traffic" },
    {
      key: "radar",
      label: "Radar ship targets",
      swatch: "radar",
      title: bundle.radar_crosscheck
        ? `${bundle.radar_crosscheck.n_targets} ship target(s) in the SAR scene, ${bundle.radar_crosscheck.n_unmatched} with no AIS association at the acquisition instant.`
        : "No radar cross check was run for this case.",
    },
  );
  if (bundle.forcing) {
    rows.push(
      { key: "current", label: "Surface current", swatch: "current", title: bundle.forcing.provenance.current_source },
      { key: "wind", label: "10 m wind", swatch: "wind", title: bundle.forcing.provenance.wind_source },
    );
  }
  const onCount = rows.filter((r) => toggles[r.key]).length;

  return (
    <div className={`layer-toggles${open ? " is-open" : ""}`} ref={rootRef}>
      <button
        type="button"
        className="map-tool-button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        title="Choose which layers are drawn"
      >
        <Layers size={16} strokeWidth={1.8} aria-hidden="true" />
        Layers
        <span className="map-tool-count mono">
          {onCount}/{rows.length}
        </span>
      </button>
      {open && (
        <div className="layer-menu">
          {rows.map((r) => (
            <label key={r.key} title={r.title} className={toggles[r.key] ? "on" : undefined}>
              <input type="checkbox" checked={toggles[r.key]} onChange={() => toggle(r.key)} />
              <span className={`layer-swatch ${r.swatch}`} aria-hidden="true" />
              {r.label}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
