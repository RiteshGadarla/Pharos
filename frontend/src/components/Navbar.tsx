import { useEffect, useState, type ReactNode } from "react";
import { FileText, ScanSearch } from "lucide-react";
import { firstAvailable } from "../api";

interface Props {
  // Candidate URLs for this case's dossier PDF, most live first. See
  // api.ts dossierCandidates.
  dossierUrls: string[];
  // The case switcher, when there is more than one case to switch
  // between. Absent in a checkout with only the single demo bundle.
  caseSwitcher?: ReactNode;
}

async function openDossier(candidates: string[]) {
  // Opened before the HEAD requests resolve and pointed afterwards, so a
  // popup blocker sees a window opened by the click itself.
  const win = window.open("", "_blank");
  const url = await firstAvailable(candidates);
  if (win) win.location.href = url;
  else window.open(url, "_blank");
}

function useUtcClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const ticker = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(ticker);
  }, []);
  return {
    time: now.toLocaleTimeString("en-GB", { timeZone: "UTC", hour: "2-digit", minute: "2-digit", second: "2-digit" }),
    date: now
      .toLocaleDateString("en-GB", { timeZone: "UTC", day: "2-digit", month: "short", year: "numeric" })
      .toUpperCase(),
  };
}

// The header carries only what the stage rail below does not: which case
// is on screen, the other pages, and the dossier. The stages themselves
// are the rail's job, and naming them twice made two navigation systems
// for the same three places.
export default function Navbar({ dossierUrls, caseSwitcher }: Props) {
  const utc = useUtcClock();

  return (
    <header className="topbar">
      {/* Full page loads to and from the other pages: they share class
          names, and each only ever loads its own stylesheet. */}
      <a className="brand" href="/" aria-label="DRISHTA home">
        <img className="brand-mark" src="/brand/drishta-mark-256.png" width={40} height={40} alt="" />
        <span className="brand-text">
          <strong>DRISHTA</strong>
          <span>MARITIME INTELLIGENCE</span>
        </span>
      </a>

      {caseSwitcher}

      <nav className="main-nav" aria-label="Pages">
        <a href="/">Overview</a>
        <a href="/inspect" title="Open the image inspector.">
          <ScanSearch size={15} strokeWidth={1.8} aria-hidden="true" />
          Inspect
        </a>
        <button type="button" onClick={() => openDossier(dossierUrls)} title="Opens this case's dossier PDF in a new tab.">
          <FileText size={15} strokeWidth={1.8} aria-hidden="true" />
          Dossier
        </button>
      </nav>

      <div className="utc" aria-label="Current time, UTC">
        <span className="mono">{utc.time}</span>
        <small>UTC · {utc.date}</small>
      </div>
    </header>
  );
}
