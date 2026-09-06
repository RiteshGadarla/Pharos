import { useEffect, useState } from "react";

// The two accumulating outputs from PLAN.md section 18, shown as plain
// tables and nothing else.
//
// Deliberately unglamorous, for the same reason the elimination log is:
// these are records, not visualisations. Do not build analytics on top
// of them. The value is that they exist and accumulate across runs, so
// that over a region and a year they become a measurement of AIS denial
// behaviour and of AIS coverage that nobody currently has.
//
// They come from the core service, so unlike everything else in this
// console they are empty in the fully offline path. That is stated
// rather than papered over: an empty ledger and an unreachable service
// are different facts.

interface DarkRow {
  mmsi: string;
  vessel_type: string;
  start: string;
  end: string;
  duration_min: number;
  resumed_course_deg: number | null;
  scene_id: string;
  unmatched_target_in_envelope: boolean;
}

interface CompletenessRow {
  scene_id: string;
  acquired_at: string;
  sensor: string;
  n_targets: number;
  n_matched: number;
  n_unmatched: number;
  unmatched_pixel_areas: number[];
}

type LoadState = "loading" | "ready" | "unavailable";

function shortTime(iso: string): string {
  return iso.replace("T", " ").slice(0, 16);
}

export default function LedgerTables() {
  const [dark, setDark] = useState<DarkRow[]>([]);
  const [completeness, setCompleteness] = useState<CompletenessRow[]>([]);
  const [state, setState] = useState<LoadState>("loading");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [d, c] = await Promise.all([
          fetch("/api/ledger/dark").then((r) => r.json()),
          fetch("/api/ledger/completeness").then((r) => r.json()),
        ]);
        if (cancelled) return;
        setDark(d.rows ?? []);
        setCompleteness(c.rows ?? []);
        setState("ready");
      } catch {
        if (!cancelled) setState("unavailable");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (state === "loading") {
    return <p className="empty-state">Reading the ledgers...</p>;
  }

  if (state === "unavailable") {
    return (
      <p className="empty-state">
        The ledgers are served by the core service, which is not running. Start it with make run-core to read
        them. Everything else on this screen comes from the offline bundle and does not need it.
      </p>
    );
  }

  return (
    <div className="ledger-tables">
      <h3 className="ledger-heading">Dark period ledger</h3>
      <p className="ledger-note">
        One row per dark period ever detected, accumulating across runs, whether or not oil was involved. It
        records AIS denial behaviour over time.
      </p>
      {dark.length === 0 ? (
        <p className="empty-state">No dark periods recorded yet.</p>
      ) : (
        <table className="ledger-table">
          <thead>
            <tr>
              <th>MMSI</th>
              <th>type</th>
              <th>start</th>
              <th>min</th>
              <th>resumed</th>
              <th>radar</th>
            </tr>
          </thead>
          <tbody>
            {dark.map((r, i) => (
              <tr key={`${r.mmsi}-${r.start}-${i}`}>
                <td className="mono">{r.mmsi}</td>
                <td>{r.vessel_type}</td>
                <td className="mono">{shortTime(r.start)}</td>
                <td className="mono">{Math.round(r.duration_min)}</td>
                <td className="mono">
                  {r.resumed_course_deg === null ? "n/a" : `${Math.round(r.resumed_course_deg)} deg`}
                </td>
                <td className="mono">{r.unmatched_target_in_envelope ? "yes" : "no"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3 className="ledger-heading">AIS completeness</h3>
      <p className="ledger-note">
        One row per processed scene, measuring how much of the AIS picture the radar image does not corroborate.
      </p>
      {completeness.length === 0 ? (
        <p className="empty-state">No scenes recorded yet.</p>
      ) : (
        <table className="ledger-table">
          <thead>
            <tr>
              <th>scene</th>
              <th>sensor</th>
              <th>hulls</th>
              <th>matched</th>
              <th>unmatched</th>
              <th>unmatched px</th>
            </tr>
          </thead>
          <tbody>
            {completeness.map((r, i) => (
              <tr key={`${r.scene_id}-${i}`}>
                <td className="mono">{r.scene_id}</td>
                <td>{r.sensor}</td>
                <td className="mono">{r.n_targets}</td>
                <td className="mono">{r.n_matched}</td>
                <td className="mono">{r.n_unmatched}</td>
                <td className="mono">{r.unmatched_pixel_areas.join(", ") || "none"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
