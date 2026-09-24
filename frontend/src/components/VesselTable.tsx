import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Ship } from "lucide-react";
import { rankOf, vesselRole, vesselSummary } from "../lib/vessel";
import { buildVesselColors, rgbToCss } from "../lib/vesselColors";
import type { DemoBundle, VesselJSON } from "../types";

interface Props {
  bundle: DemoBundle;
  hoveredMmsi: string | null;
  selectedMmsi: string | null;
  onHoverVessel: (mmsi: string | null) => void;
  onSelectVessel: (mmsi: string | null) => void;
}

const POPOVER_WIDTH = 260;
const POPOVER_GAP = 10;

// A little extra, beyond the row's own columns, for the hover card:
// whatever this vessel has on top of mmsi/type/rank that does not fit a
// row without turning the table back into the thing it replaced.
function extraLines(bundle: DemoBundle, vessel: VesselJSON): string[] {
  const lines: string[] = [vesselSummary(bundle, vessel)];
  lines.push(`${vessel.points.length} AIS report${vessel.points.length === 1 ? "" : "s"}`);
  if (vessel.dark_gaps.length > 0) {
    const totalMin = vessel.dark_gaps.reduce((sum, g) => sum + g.duration_min, 0);
    lines.push(`${vessel.dark_gaps.length} dark period${vessel.dark_gaps.length > 1 ? "s" : ""}, ${Math.round(totalMin)} min total`);
  }
  if (vessel.integrity_flags && vessel.integrity_flags.length > 0) {
    lines.push(`${vessel.integrity_flags.length} AIS integrity flag${vessel.integrity_flags.length > 1 ? "s" : ""}`);
  }
  const timing = bundle.vessel_timing?.[vessel.mmsi];
  if (timing?.statement) lines.push(timing.statement);
  if (vessel.score?.radar_support) lines.push(`Radar support: ${vessel.score.radar_support}`);
  return lines;
}

// Every vessel in the case, one row each, numbered and coloured to match
// its track on the map. The map makes clicking a specific line hard once
// several cross in a small area; this is the alternative way in — a row
// is always easy to click, and picking one does exactly what clicking
// its line would. Behind a single button so it costs nothing when
// closed, the same pattern as LayerToggles just beside it.
export default function VesselTable({ bundle, hoveredMmsi, selectedMmsi, onHoverVessel, onSelectVessel }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  // The hover popover is portaled to <body> and positioned in fixed
  // coordinates from the row's own bounding box, rather than a CSS
  // absolute child of the row: the row list scrolls (max-height, so
  // seventeen vessels stay a small table), and a scrolling ancestor
  // clips absolutely positioned descendants that try to escape it
  // sideways no matter what overflow-x is set to.
  const [popover, setPopover] = useState<{ mmsi: string; top: number; left: number } | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  useEffect(() => {
    if (!open) setPopover(null);
  }, [open]);

  const colors = useMemo(() => buildVesselColors(bundle), [bundle]);
  const vesselByMmsi = useMemo(() => new Map(bundle.vessels.map((v) => [v.mmsi, v])), [bundle]);

  // Ranked survivors first, in rank order, then the eliminated in the
  // order they were cleared — the same order the vessel-focus card steps
  // through, so a row number here means the same thing there.
  const order = useMemo(
    () => [...bundle.suspects.map((s) => s.mmsi), ...bundle.eliminations.map((e) => e.mmsi)],
    [bundle],
  );

  const popoverVessel = popover ? vesselByMmsi.get(popover.mmsi) : null;

  return (
    <div className={`vessel-table${open ? " is-open" : ""}`} ref={rootRef}>
      <button
        type="button"
        className="map-tool-button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        title="Every vessel in the window, as a table"
      >
        <Ship size={16} strokeWidth={1.8} aria-hidden="true" />
        Vessels
        <span className="map-tool-count mono">{order.length}</span>
      </button>
      {open && (
        <div className="vessel-table-menu">
          <div className="vessel-table-head">
            <span className="vt-col-num">#</span>
            <span className="vt-col-swatch" aria-hidden="true" />
            <span className="vt-col-mmsi">MMSI</span>
            <span className="vt-col-type">Type</span>
            <span className="vt-col-status">Status</span>
          </div>
          <div className="vessel-table-rows">
            {order.map((mmsi, i) => {
              const vessel = vesselByMmsi.get(mmsi);
              if (!vessel) return null;
              const color = rgbToCss(colors.get(mmsi) ?? [144, 165, 175]);
              const rank = rankOf(bundle, mmsi);
              const role = vesselRole(vessel, bundle.culprit_mmsi);
              const isFocused = mmsi === hoveredMmsi || mmsi === selectedMmsi;
              return (
                <div
                  key={mmsi}
                  className={`vessel-table-row${isFocused ? " focused" : ""}`}
                  style={{ borderLeftColor: color }}
                  onMouseEnter={(e) => {
                    onHoverVessel(mmsi);
                    const rect = e.currentTarget.getBoundingClientRect();
                    setPopover({ mmsi, top: rect.top, left: rect.left });
                  }}
                  onMouseLeave={() => {
                    onHoverVessel(null);
                    setPopover(null);
                  }}
                  onClick={() => {
                    onSelectVessel(mmsi);
                    setOpen(false);
                  }}
                >
                  <span className="vt-col-num mono">{i + 1}</span>
                  <span className="vt-col-swatch" style={{ background: color }} aria-hidden="true" />
                  <span className="vt-col-mmsi mono">{mmsi}</span>
                  <span className="vt-col-type">{vessel.vessel_type}</span>
                  <span className="vt-col-status">
                    {role === "eliminated" ? (
                      <span className="pill status-eliminated">Eliminated</span>
                    ) : (
                      <span className={`pill status-${role}`}>Rank {rank}</span>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
      {open &&
        popover &&
        popoverVessel &&
        createPortal(
          <div
            className="vessel-row-popover"
            style={{ top: popover.top, left: Math.max(8, popover.left - POPOVER_WIDTH - POPOVER_GAP), width: POPOVER_WIDTH }}
          >
            {extraLines(bundle, popoverVessel).map((line, j) => (
              <p key={j}>{line}</p>
            ))}
          </div>,
          document.body,
        )}
    </div>
  );
}
