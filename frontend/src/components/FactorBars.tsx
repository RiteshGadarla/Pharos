import { FACTOR_LABELS } from "../types";

interface Props {
  factors: Record<string, number>;
  digits?: number;
}

// A vessel's named factors as signed bars from a centre line, largest
// first. Centred because a factor can be negative: evidence that counts
// against a vessel is as real as evidence for it, and bars that only
// grow rightwards hide half the model. Bars grow from zero when they
// appear (PLAN.md 16A, layer 4) and never move otherwise.
export default function FactorBars({ factors, digits = 2 }: Props) {
  const entries = Object.entries(factors).sort((a, b) => b[1] - a[1]);
  const maxAbs = Math.max(1e-6, ...entries.map(([, v]) => Math.abs(v)));

  return (
    <div className="factor-bars">
      {entries.map(([name, value]) => {
        const pct = (Math.abs(value) / maxAbs) * 50;
        const [code, ...rest] = (FACTOR_LABELS[name] ?? name).split(" ");
        return (
          <div className={`factor-row${value === 0 ? " zero" : ""}`} key={name} title={FACTOR_LABELS[name] ?? name}>
            <span className="factor-code mono">{code}</span>
            <span className="factor-label">{rest.join(" ")}</span>
            <span className="factor-track">
              <span className="factor-zero" />
              <span
                className={`factor-fill ${value < 0 ? "negative" : "positive"}`}
                style={{ width: `${pct}%`, left: value < 0 ? `${50 - pct}%` : "50%" }}
              />
            </span>
            <span className={`factor-value mono${value < 0 ? " negative" : ""}`}>
              {value > 0 ? "+" : ""}
              {value.toFixed(digits)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
