import { useId, useState, type ReactNode } from "react";

interface Props {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
  // A colour key beside the title, for sections that describe a layer
  // drawn on the map in that colour.
  swatch?: "backward" | "forward" | "window" | "provenance";
  // Marks the section describing what the map is drawing right now.
  live?: boolean;
}

// One collapsible section of the side panel. Collapsing keeps the panel
// short enough that it never needs a scrollbar of its own; the content
// underneath is unchanged whether it is open or not.
export default function Accordion({ title, children, defaultOpen = false, swatch, live = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const contentId = useId();

  return (
    <section className={`accordion${open ? " is-open" : ""}${live ? " is-live" : ""}`}>
      <button
        type="button"
        className="accordion-header"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={contentId}
      >
        {swatch && <span className={`accordion-swatch ${swatch}`} aria-hidden="true" />}
        <span className="accordion-title">{title}</span>
        {live && <span className="accordion-live-chip">ON SCREEN</span>}
        <span className="accordion-arrow" aria-hidden="true">
          {open ? "↑" : "↓"}
        </span>
      </button>
      {/* Collapsed by animating the grid row to zero rather than removing
          the content, so it can slide. inert keeps the hidden half out of
          the tab order. */}
      <div id={contentId} className={`accordion-content${open ? " open" : ""}`} inert={!open}>
        <div className="accordion-inner">{children}</div>
      </div>
    </section>
  );
}
