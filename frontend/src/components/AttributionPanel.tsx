import Accordion from "./Accordion";
import CaseBuildPanel from "./CaseBuildPanel";
import EliminationLog from "./EliminationLog";
import LedgerTables from "./LedgerTables";
import SuspectsPanel from "./SuspectsPanel";
import VerdictCard from "./VerdictCard";
import VesselFocusCard from "./VesselFocusCard";
import type { DemoBundle } from "../types";

export type AttributionSection = "case" | "suspects" | "eliminations";

interface Props {
  bundle: DemoBundle;
  timeMs: number;
  section: AttributionSection;
  onSectionChange: (section: AttributionSection) => void;
  hoveredMmsi: string | null;
  selectedMmsi: string | null;
  onHoverVessel: (mmsi: string | null) => void;
  onSelectVessel: (mmsi: string | null) => void;
}

// Stage 3's side panel, in one of two states and never both at once.
//
// With no vessel selected it is the case: the verdict at the top, then
// one of three views of the working below it. With a vessel selected it
// is that vessel's story, full height, with one way back. Stacking the
// vessel above the case put three levels of heading on screen before
// any content, and a room cannot tell which of them is the answer.
//
// The ledgers live with the elimination log because both are records
// rather than findings, and neither needs its own tab.
export default function AttributionPanel({
  bundle,
  timeMs,
  section,
  onSectionChange,
  hoveredMmsi,
  selectedMmsi,
  onHoverVessel,
  onSelectVessel,
}: Props) {
  if (selectedMmsi) {
    return (
      <div className="pane-scroll">
        <VesselFocusCard
          bundle={bundle}
          mmsi={selectedMmsi}
          timeMs={timeMs}
          onClear={() => onSelectVessel(null)}
          onStep={onSelectVessel}
        />
      </div>
    );
  }

  const tabs: { key: AttributionSection; label: string; count?: number }[] = [];
  if (bundle.case_build) tabs.push({ key: "case", label: "Case build" });
  tabs.push(
    { key: "suspects", label: "Suspects", count: bundle.suspects.length },
    { key: "eliminations", label: "Eliminated", count: bundle.eliminations.length },
  );
  const active = tabs.some((t) => t.key === section) ? section : tabs[0].key;

  return (
    <>
      <VerdictCard bundle={bundle} onFocusVessel={onSelectVessel} />
      <div className="segmented" role="tablist" aria-label="The working">
        {tabs.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={active === t.key}
            className={active === t.key ? "active" : ""}
            onClick={() => onSectionChange(t.key)}
          >
            {t.label}
            {t.count !== undefined && <span className="segmented-count mono">{t.count}</span>}
          </button>
        ))}
      </div>
      <div className="pane-scroll">
        {active === "case" && <CaseBuildPanel bundle={bundle} onFocusVessel={onSelectVessel} />}
        {active === "suspects" && (
          <SuspectsPanel
            bundle={bundle}
            hoveredMmsi={hoveredMmsi}
            selectedMmsi={selectedMmsi}
            onHoverVessel={onHoverVessel}
            onSelectVessel={onSelectVessel}
          />
        )}
        {active === "eliminations" && (
          <>
            <EliminationLog bundle={bundle} onFocusVessel={onSelectVessel} onHoverVessel={onHoverVessel} />
            <div className="panel-accordions">
              <Accordion title="Ledgers across runs">
                <LedgerTables />
              </Accordion>
            </div>
          </>
        )}
      </div>
    </>
  );
}
