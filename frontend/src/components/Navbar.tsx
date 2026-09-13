import { useEffect, useState } from "react";
import { Waves } from "lucide-react";

export type RightTab = "case" | "suspects" | "eliminations" | "ledgers";

interface Props {
  stage: number;
  rightTab: RightTab;
  onNavigate: (stage: number, tab?: RightTab) => void;
}

type NavItem =
  | { label: string; href: string }
  | { label: string; stage: number; tab?: RightTab }
  | { label: string; dossier: true };

// Every item goes somewhere different. The stage rail below already
// steps through the three stages; this adds the two stage 3 tabs a
// presenter is most often asked for, the way back to the landing page,
// and the dossier.
const NAV_ITEMS: NavItem[] = [
  { label: "OVERVIEW", href: "/" },
  { label: "DETECTION", stage: 1 },
  { label: "ORIGIN", stage: 2 },
  { label: "TRAFFIC", stage: 3, tab: "suspects" },
  { label: "EVIDENCE", stage: 3, tab: "case" },
  { label: "CASES", dossier: true },
];

// Stage 3 has four tabs and two nav items: the case build is EVIDENCE,
// every other tab is the traffic it was derived from.
function activeLabel(stage: number, tab: RightTab): string {
  if (stage === 1) return "DETECTION";
  if (stage === 2) return "ORIGIN";
  return tab === "case" ? "EVIDENCE" : "TRAFFIC";
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

export default function Navbar({ stage, rightTab, onNavigate }: Props) {
  const utc = useUtcClock();
  const active = activeLabel(stage, rightTab);

  return (
    <header className="topbar">
      {/* Full page loads to and from the landing page: the two pages share
          class names, and each only ever loads its own stylesheet. */}
      <a className="brand" href="/" aria-label="DRISHTA home">
        <div className="brand-mark">
          <Waves size={42} strokeWidth={1.4} />
        </div>
        <div className="brand-text">
          <strong>DRISHTA</strong>
          <span>MARITIME INTELLIGENCE</span>
        </div>
      </a>

      <nav className="main-nav">
        {NAV_ITEMS.map((item) => {
          const className = item.label === active ? "active" : undefined;
          if ("href" in item) {
            return (
              <a key={item.label} className={className} href={item.href}>
                {item.label}
              </a>
            );
          }
          return (
            <button
              key={item.label}
              type="button"
              className={className}
              onClick={"dossier" in item ? openDossier : () => onNavigate(item.stage, item.tab)}
              title={"dossier" in item ? "Opens the case dossier PDF in a new tab." : undefined}
            >
              {item.label}
            </button>
          );
        })}
      </nav>

      <div className="status">
        <i />
        SYSTEM READY
      </div>

      <div className="utc">
        <span>UTC&nbsp; {utc.time}</span>
        <small>{utc.date}</small>
      </div>
    </header>
  );
}
