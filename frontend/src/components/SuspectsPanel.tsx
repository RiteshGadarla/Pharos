import { useState } from "react";
import { ArrowRight } from "lucide-react";
import Disclosure from "./Disclosure";
import FactorBars from "./FactorBars";
import type { DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
  hoveredMmsi: string | null;
  selectedMmsi: string | null;
  onHoverVessel: (mmsi: string | null) => void;
  onSelectVessel: (mmsi: string | null) => void;
}

// The ranked survivors. A row expands to its factor bars in place, and
// hovering one lights its track on the map. Following a vessel is its own
// button, because it swaps the panel for that vessel's story and an
// expand should not do that by surprise.
export default function SuspectsPanel({ bundle, hoveredMmsi, selectedMmsi, onHoverVessel, onSelectVessel }: Props) {
  const [expanded, setExpanded] = useState<string | null>(bundle.culprit_mmsi);
  const maxTotal = Math.max(...bundle.suspects.map((s) => s.total), 1e-6);
  const vesselByMmsi = new Map(bundle.vessels.map((v) => [v.mmsi, v]));

  return (
    <div className="suspects-panel">
      {bundle.suspects.map((s) => {
        const vessel = vesselByMmsi.get(s.mmsi);
        const isOpen = expanded === s.mmsi;
        const isFocused = s.mmsi === hoveredMmsi || s.mmsi === selectedMmsi;
        // Ranks 1-3 each carry their own colour, matching the same three
        // colours the map gives those vessels' tracks and dots, so a row
        // here and a line there can be told apart as the same vessel on
        // sight rather than by hovering to check.
        const rankClass = s.rank >= 1 && s.rank <= 3 ? ` rank${s.rank}` : "";
        return (
          <div
            key={s.mmsi}
            className={`suspect-row${isFocused ? " focused" : ""}${rankClass}${isOpen ? " open" : ""}`}
            onMouseEnter={() => onHoverVessel(s.mmsi)}
            onMouseLeave={() => onHoverVessel(null)}
          >
            <button className="suspect-summary" onClick={() => setExpanded(isOpen ? null : s.mmsi)} aria-expanded={isOpen}>
              <span className="suspect-rank mono">#{s.rank}</span>
              <span className="suspect-id">
                <span className="suspect-mmsi mono">{s.mmsi}</span>
                <span className="suspect-type">{vessel?.vessel_type ?? ""}</span>
              </span>
              <span className="suspect-bar-track">
                <span className="suspect-bar-fill" style={{ width: `${Math.max(3, (Math.max(0, s.total) / maxTotal) * 100)}%` }} />
              </span>
              <span className="suspect-total mono">{s.total.toFixed(2)}</span>
            </button>
            {isOpen && (
              <div className="suspect-detail">
                <FactorBars factors={s.factors} digits={3} />
                {s.radar_support && (
                  <p className="suspect-radar">
                    Radar support: <span className="mono">{s.radar_support}</span>. An unmatched ship target in the SAR
                    scene fell inside this vessel's dead-reckoned dark envelope, over live origin field mass.
                  </p>
                )}
                {vessel?.integrity_flags && vessel.integrity_flags.length > 0 && (
                  <ul className="flag-list">
                    {vessel.integrity_flags.map((flag, i) => (
                      <li key={`${flag.kind}-${i}`}>
                        <span className="mono">{flag.kind}</span> {flag.detail}
                      </li>
                    ))}
                  </ul>
                )}
                <div className="suspect-actions">
                  <Disclosure label="In plain words">
                    <p>{s.narrative}</p>
                  </Disclosure>
                  <button className="link-button" onClick={() => onSelectVessel(s.mmsi)}>
                    Follow on the map
                    <ArrowRight size={15} strokeWidth={1.8} aria-hidden="true" />
                  </button>
                </div>
              </div>
            )}
          </div>
        );
      })}
      {bundle.suspects.length === 0 && <p className="empty-state">No vessel survived elimination in this scenario.</p>}
    </div>
  );
}
