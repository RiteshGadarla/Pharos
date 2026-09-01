import type { ViewKey, ViewPreset } from "../lib/views";

interface Props {
  presets: ViewPreset[];
  active: ViewKey;
  onSelect: (key: ViewKey) => void;
}

export default function ViewPresets({ presets, active, onSelect }: Props) {
  return (
    <div className="view-presets" role="group" aria-label="Map view">
      <span className="view-presets-label">VIEW</span>
      {presets.map((p) => (
        <button
          key={p.key}
          className={p.key === active ? "active" : ""}
          title={p.title}
          onClick={() => onSelect(p.key)}
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}
