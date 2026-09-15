import type { ReactNode } from "react";

interface Props {
  label: string;
  value: ReactNode;
  unit?: string;
  sub?: ReactNode;
  // "hero" is the one number a panel is about. Everything else is "md"
  // or "sm", so the eye has exactly one place to land first.
  size?: "hero" | "lg" | "md" | "sm";
  tone?: "default" | "oil" | "forecast" | "suspect" | "cleared" | "radar" | "accent" | "muted";
  mono?: boolean;
  title?: string;
}

export default function Stat({ label, value, unit, sub, size = "md", tone = "default", mono = true, title }: Props) {
  return (
    <div className={`stat stat-${size} tone-${tone}`} title={title}>
      <span className="stat-label">{label}</span>
      <span className={`stat-value${mono ? " mono" : ""}`}>
        {value}
        {unit && <span className="stat-unit">{unit}</span>}
      </span>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  );
}
