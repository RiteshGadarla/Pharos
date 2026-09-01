import type { DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
}

// Deliberately unglamorous, PLAN.md section 12: "Its job is to look
// like a record, not a visualisation."
export default function EliminationLog({ bundle }: Props) {
  const vesselByMmsi = new Map(bundle.vessels.map((v) => [v.mmsi, v]));

  if (bundle.eliminations.length === 0) {
    return <p className="empty-state">No vessel was eliminated in this scenario.</p>;
  }

  return (
    <table className="elimination-table">
      <thead>
        <tr>
          <th>MMSI</th>
          <th>Type</th>
          <th>Rule</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
        {bundle.eliminations.map((e) => (
          <tr key={e.mmsi}>
            <td className="mono">{e.mmsi}</td>
            <td>{vesselByMmsi.get(e.mmsi)?.vessel_type ?? ""}</td>
            <td className="mono">{e.rule}</td>
            <td>{e.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
