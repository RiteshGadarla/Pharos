import type { DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
  onFocusVessel?: (mmsi: string) => void;
  onHoverVessel?: (mmsi: string | null) => void;
}

// Deliberately unglamorous, PLAN.md section 16: "Its job is to look
// like a record, not a visualisation." One line per vessel: who, the
// rule that cleared it, and the reason written as a sentence an
// investigator would accept.
export default function EliminationLog({ bundle, onFocusVessel, onHoverVessel }: Props) {
  const vesselByMmsi = new Map(bundle.vessels.map((v) => [v.mmsi, v]));

  if (bundle.eliminations.length === 0) {
    return <p className="empty-state">No vessel was eliminated in this scenario.</p>;
  }

  return (
    <table className="elimination-table">
      <thead>
        <tr>
          <th>Vessel</th>
          <th>Rule and reason</th>
        </tr>
      </thead>
      <tbody>
        {bundle.eliminations.map((e) => (
          <tr
            key={e.mmsi}
            onClick={onFocusVessel ? () => onFocusVessel(e.mmsi) : undefined}
            onMouseEnter={onHoverVessel ? () => onHoverVessel(e.mmsi) : undefined}
            onMouseLeave={onHoverVessel ? () => onHoverVessel(null) : undefined}
            className={onFocusVessel ? "clickable" : undefined}
            title={onFocusVessel ? "Follow this vessel on the map" : undefined}
          >
            <td>
              <span className="mono elim-mmsi">{e.mmsi}</span>
              <span className="elim-type">{vesselByMmsi.get(e.mmsi)?.vessel_type ?? ""}</span>
            </td>
            <td>
              <span className="mono elim-rule">{e.rule}</span>
              <span className="elim-reason">{e.reason}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
