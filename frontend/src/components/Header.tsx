import type { DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
}

async function openDossier() {
  try {
    const res = await fetch("/api/dossier", { method: "HEAD" });
    if (res.ok) {
      window.open("/api/dossier", "_blank");
      return;
    }
  } catch {
    // core service not running, fall through to the static copy
  }
  window.open("/data/case_dossier.pdf", "_blank");
}

export default function Header({ bundle }: Props) {
  return (
    <header className="app-header">
      <div className="wordmark">DRISHTA</div>
      <div className="case-chip" title={`${bundle.incident_context.status}\n\nSource reference: ${bundle.incident_context.source_reference}`}>
        <span className="chip-label">CASE</span>
        <span className="mono">{bundle.case_id}</span>
      </div>
      <div className="case-chip">
        <span className="chip-label">SCENE</span>
        <span className="mono">{bundle.scene.scene_id}</span>
        <span className="mono muted">{bundle.scene.acquired_at.replace("T", " ").slice(0, 16)} UTC</span>
        {/* Which sensor adapter read the scene (PLAN.md section 5A).
            On screen for the same reason it is on the dossier's
            provenance page: sensor agnosticism is a claim, and this is
            where it is demonstrated rather than asserted. */}
        <span className="mono muted">{bundle.scene.sensor ?? "S1"}</span>
      </div>
      <div className="case-chip" title={bundle.status_note}>
        <span className="chip-label">PROVENANCE</span>
        <span className="mono">
          ensemble n={bundle.origin_field.n_members}, seed={bundle.origin_field.seed}
          {bundle.origin_field.kernel ? `, kernel ${bundle.origin_field.kernel}` : ""}
        </span>
      </div>
      <div className="spacer" />
      <span className="offline-badge">DEMO MODE: OFFLINE</span>
      <button className="dossier-button" onClick={openDossier} title="Opens the case dossier PDF in a new tab.">
        Download dossier
      </button>
    </header>
  );
}
