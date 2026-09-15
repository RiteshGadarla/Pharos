import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import type { CaseSummary } from "../types";

interface Props {
  cases: CaseSummary[];
  activeId: string | null;
  loadingId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (id: string) => void;
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return Boolean(el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable));
}

// The case studies, switchable from the header in one keystroke.
//
// The cases differ by wind regime and verdict class, so those two are
// what the closed button and every row lead with: a room should be able
// to see why the next case is worth showing before it loads.
//
// C opens it, a number picks a case, Escape closes it. The listener runs
// in the capture phase and marks the keys it uses as handled, so the
// console's own stage shortcuts (number keys among them) stay out of
// the way while the list is open.
export default function CaseSwitcher({ cases, activeId, loadingId, open, onOpenChange, onSelect }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const activeIndex = Math.max(0, cases.findIndex((c) => c.id === activeId));
  const [highlight, setHighlight] = useState(activeIndex);
  const active = cases.find((c) => c.id === activeId) ?? null;

  // The highlight starts on the case already showing, set as the list
  // opens rather than in an effect after it has rendered.
  const setOpen = useCallback(
    (next: boolean) => {
      if (next) setHighlight(activeIndex);
      onOpenChange(next);
    },
    [activeIndex, onOpenChange],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
      const key = e.key.toLowerCase();
      if (!open) {
        if (key === "c") {
          e.preventDefault();
          setOpen(true);
        }
        return;
      }
      if (key === "tab") return;
      e.preventDefault();
      if (key === "escape" || key === "c") setOpen(false);
      else if (key === "arrowdown") setHighlight((h) => (h + 1) % cases.length);
      else if (key === "arrowup") setHighlight((h) => (h - 1 + cases.length) % cases.length);
      else if (key === "enter") onSelect(cases[highlight].id);
      else if (/^[1-9]$/.test(key) && Number(key) <= cases.length) onSelect(cases[Number(key) - 1].id);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, cases, highlight, setOpen, onSelect]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open, setOpen]);

  return (
    <div className={`case-switcher${open ? " is-open" : ""}`} ref={rootRef}>
      <button
        type="button"
        className="case-switcher-button"
        onClick={() => setOpen(!open)}
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Switch case study (C)"
      >
        <span className="case-switcher-kicker">
          Case {activeIndex + 1}/{cases.length}
        </span>
        <span className="case-switcher-title">{loadingId ? "Loading case..." : (active?.title ?? "Choose a case")}</span>
        {active && !loadingId && (
          <>
            <span className={`verdict-chip verdict-${active.verdict.toLowerCase()}`}>
              {active.verdict.replace("_", " ")}
            </span>
            <span className="case-switcher-wind mono">{active.wind_ms.toFixed(1)} m/s</span>
          </>
        )}
        <kbd className="kbd">C</kbd>
        <ChevronDown size={16} strokeWidth={2} aria-hidden="true" className="case-switcher-chevron" />
      </button>

      {open && (
        <div className="case-menu" role="listbox" aria-label="Case studies">
          <div className="case-menu-head">
            <span>Case studies</span>
            <span className="case-menu-hint">
              <kbd className="kbd">1</kbd> to <kbd className="kbd">{cases.length}</kbd> to open,{" "}
              <kbd className="kbd">Esc</kbd> to close
            </span>
          </div>
          {cases.map((c, i) => {
            const isActive = c.id === activeId;
            return (
              <button
                key={c.id}
                type="button"
                role="option"
                aria-selected={isActive}
                className={`case-option${isActive ? " active" : ""}${i === highlight ? " highlight" : ""}`}
                onMouseEnter={() => setHighlight(i)}
                onClick={() => onSelect(c.id)}
              >
                <kbd className="kbd case-option-key">{i + 1}</kbd>
                <span className="case-option-main">
                  <span className="case-option-title">
                    {c.title}
                    {isActive && <span className="case-option-current">showing</span>}
                  </span>
                  <span className="case-option-subtitle">{c.subtitle}</span>
                  <span className="case-option-meta mono">
                    {c.region} · {c.n_vessels} vessels · {c.n_eliminated} eliminated · {c.n_suspects} suspect
                    {c.n_suspects === 1 ? "" : "s"}
                  </span>
                </span>
                <span className="case-option-side">
                  <span className={`verdict-chip verdict-${c.verdict.toLowerCase()}`}>{c.verdict.replace("_", " ")}</span>
                  <span className="case-option-wind">
                    <span className="mono case-option-wind-value">{c.wind_ms.toFixed(1)}</span>
                    <span className="case-option-wind-unit">m/s wind</span>
                  </span>
                  <span className="case-option-wind-summary">
                    {c.wind_summary}
                    {c.gate_verdict !== "accept" && <span className={`gate-inline gate-${c.gate_verdict}`}> gate {c.gate_verdict}</span>}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
