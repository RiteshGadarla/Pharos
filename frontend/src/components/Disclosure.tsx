import { useId, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

interface Props {
  // What the hidden text answers, so the button names what happens:
  // "Why accepted", "How this is measured".
  label: string;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
}

// The reasoning behind a number, one click away from it.
//
// Every panel leads with the figure or the verdict and keeps the
// sentences that justify it here. Nothing is removed: the text is the
// same text the panel always carried, it just stops competing with the
// number for the room's attention until someone asks.
export default function Disclosure({ label, children, defaultOpen = false, className }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div className={`disclosure${open ? " is-open" : ""}${className ? ` ${className}` : ""}`}>
      <button
        type="button"
        className="disclosure-toggle"
        aria-expanded={open}
        aria-controls={id}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
      >
        <span>{label}</span>
        <ChevronDown size={14} strokeWidth={2} aria-hidden="true" className="disclosure-chevron" />
      </button>
      <div id={id} className={`disclosure-body${open ? " open" : ""}`} inert={!open}>
        <div className="disclosure-inner">{children}</div>
      </div>
    </div>
  );
}
