import { useState } from "react";
import { FACTOR_LABELS, type DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
  hoveredMmsi: string | null;
  selectedMmsi: string | null;
  onHoverVessel: (mmsi: string | null) => void;
  onSelectVessel: (mmsi: string | null) => void;
}

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
        const isCulprit = s.mmsi === bundle.culprit_mmsi;
        return (
          <div
            key={s.mmsi}
            className={`suspect-row ${isFocused ? "focused" : ""} ${isCulprit ? "rank1" : ""}`}
            onMouseEnter={() => onHoverVessel(s.mmsi)}
            onMouseLeave={() => onHoverVessel(null)}
            onClick={() => {
              onSelectVessel(s.mmsi);
              setExpanded(isOpen ? null : s.mmsi);
            }}
          >
            <div className="suspect-summary">
              <span className="suspect-rank">#{s.rank}</span>
              <span className="suspect-mmsi">{s.mmsi}</span>
              <span className="suspect-type">{vessel?.vessel_type ?? ""}</span>
              <div className="suspect-bar-track">
                <div
                  className="suspect-bar-fill"
                  style={{ width: `${Math.max(4, (s.total / maxTotal) * 100)}%` }}
                />
              </div>
              <span className="suspect-total">{s.total.toFixed(2)}</span>
            </div>
            {isOpen && (
              <div className="suspect-detail">
                {Object.entries(s.factors)
                  .sort((a, b) => b[1] - a[1])
                  .map(([name, value]) => {
                    const maxFactor = Math.max(...Object.values(s.factors).map((v) => Math.abs(v)), 1e-6);
                    const widthPct = Math.max(2, (Math.abs(value) / maxFactor) * 100);
                    return (
                      <div className="factor-row" key={name}>
                        <span className="factor-label">{FACTOR_LABELS[name] ?? name}</span>
                        <div className="factor-bar-track">
                          <div
                            className={`factor-bar-fill ${value < 0 ? "negative" : ""}`}
                            style={{ width: `${widthPct}%` }}
                          />
                        </div>
                        <span className="factor-value">{value.toFixed(3)}</span>
                      </div>
                    );
                  })}
                <p className="suspect-narrative">{s.narrative}</p>
              </div>
            )}
          </div>
        );
      })}
      {bundle.suspects.length === 0 && <p className="empty-state">No vessel survived elimination in this scenario.</p>}
    </div>
  );
}
