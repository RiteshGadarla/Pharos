import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import Disclosure from "./Disclosure";
import { FACTOR_LABELS, type DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
  onFocusVessel: (mmsi: string) => void;
}

// The case assembling itself, one class of evidence at a time.
//
// Stage 3 used to end at a ranked list. A ranking is a result, and the
// only things a room can do with a result are accept it or reject it.
// Every competing system produces one.
//
// This system's scoring is an explicit weighted model with named factors
// and no learned parameters, which means the case can be taken apart and
// put back together in front of the room. Stepping through it shows
// which evidence actually did the work, and the two lines at the bottom
// say where the answer settled and whether any single factor decides it.
//
// On the shipped 48 hour case the leader settles at the first scored
// step and never moves, so what this shows is a lead that survives
// every later piece of evidence rather than a dramatic flip. Do not
// write copy here that promises a flip: on the 6h test fixture position
// alone does pick the wrong vessel and behaviour corrects it, and a
// comment describing that case as if it were this one is how the panel
// ends up narrating a scenario the bundle does not contain.
//
// The answer to "this is just proximity" lives in the baselines below
// instead, and it is stronger for being measured: nearest-to-centroid
// collapses the field to a point and names a different vessel.
//
// The nine steps are a single row of numbered stops rather than a list,
// so the step being shown, its question and its bars get the space. Each
// stop still names its step on hover, and the result of each baseline
// stays visible while what it assumes sits one click down.
export default function CaseBuildPanel({ bundle, onFocusVessel }: Props) {
  const build = bundle.case_build;
  const [index, setIndex] = useState<number>(() => (build ? build.steps.length - 1 : 0));

  if (!build) return null;

  const step = build.steps[Math.min(index, build.steps.length - 1)];
  const maxAbs = Math.max(1e-6, ...step.ranking.map((r) => Math.abs(r.total)));
  const settlesAt = build.steps.find((s) => s.key === build.stabilises_at_step);
  const settlesOrdinal = settlesAt ? build.steps.indexOf(settlesAt) + 1 : null;
  const robust = build.decisive_factors.length === 0;

  return (
    <section className="case-build">
      <div className="case-head">
        <h3 className="section-title">How the case was built</h3>
        <div className="case-nav">
          <button onClick={() => setIndex((i) => Math.max(0, i - 1))} disabled={index === 0} aria-label="Previous evidence">
            <ChevronLeft size={18} strokeWidth={1.8} aria-hidden="true" />
          </button>
          <span className="case-counter mono">
            {index + 1}/{build.steps.length}
          </span>
          <button
            onClick={() => setIndex((i) => Math.min(build.steps.length - 1, i + 1))}
            disabled={index === build.steps.length - 1}
            aria-label="Add next evidence"
            title="Add next evidence"
          >
            <ChevronRight size={18} strokeWidth={1.8} aria-hidden="true" />
          </button>
        </div>
      </div>

      {/* Each step is directly clickable, not just next and back: during
          questions a room asks about one specific piece of evidence. */}
      <ol className="case-track">
        {build.steps.map((s, i) => (
          <li key={s.key}>
            <button
              className={`case-stop ${i === index ? "current" : i < index ? "done" : ""}${s.lead_changed ? " flips" : ""}${
                s.key === build.stabilises_at_step ? " settles" : ""
              }`}
              onClick={() => setIndex(i)}
              title={`${i + 1}. ${s.label}: ${s.question}${s.lead_changed ? " (lead changes)" : ""}`}
              aria-label={`${i + 1}. ${s.label}`}
              aria-current={i === index ? "step" : undefined}
            >
              <span className="mono">{i + 1}</span>
            </button>
          </li>
        ))}
      </ol>

      <div className="case-step">
        <span className="case-step-label">
          {step.label}
          {step.lead_changed && <span className="pill flip">Lead changes</span>}
        </span>
        <p className="case-question">{step.question}</p>
        <p className="case-note">{step.note}</p>

        {step.factors_added.length > 0 && (
          <p className="case-factors">
            {step.factors_added.map((f) => (
              <span className="case-factor-chip mono" key={f}>
                + {FACTOR_LABELS[f] ?? f}
              </span>
            ))}
          </p>
        )}

        {step.ranking.length > 0 && (
          <div className="case-bars">
            {step.ranking.map((r) => (
              <button
                className={`case-bar-row ${r.mmsi === build.final_lead ? "final-lead" : ""}`}
                key={r.mmsi}
                onClick={() => onFocusVessel(r.mmsi)}
                title="Show this vessel on the map"
              >
                <span className="case-bar-rank mono">#{r.rank}</span>
                <span className="case-bar-mmsi mono">{r.mmsi}</span>
                <span className="case-bar-track">
                  {/* Bars run from a centre line because a score can be
                      negative: evidence that counts against a vessel is
                      as real as evidence for it, and a bar chart that
                      only grows rightwards hides half the model. */}
                  <span className="case-bar-zero" />
                  <span
                    className={`case-bar-fill ${r.total < 0 ? "negative" : ""}`}
                    style={{
                      width: `${(Math.abs(r.total) / maxAbs) * 50}%`,
                      left: r.total < 0 ? `${50 - (Math.abs(r.total) / maxAbs) * 50}%` : "50%",
                    }}
                  />
                </span>
                <span className="case-bar-total mono">{r.total.toFixed(2)}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* The two claims worth holding the system to. Both are computed,
          and the second can come out against us, in which case it is
          shown in the same place at the same size. */}
      <div className={`case-robustness ${robust ? "robust" : "fragile"}`}>
        <div className="case-robust-grid">
          <div className="case-robust-cell">
            <span className="stat-label">Settles at</span>
            <span className="case-robust-value">
              {settlesAt ? (
                <>
                  <span className="mono">{settlesOrdinal}</span> {settlesAt.label}
                </>
              ) : (
                "never"
              )}
            </span>
          </div>
          <div className="case-robust-cell">
            <span className="stat-label">Leave one out</span>
            <span className="case-robust-value">
              {robust ? "No single factor decides it" : build.decisive_factors.map((f) => FACTOR_LABELS[f] ?? f).join(", ")}
            </span>
          </div>
        </div>
        <Disclosure label="What this means">
          <p>{build.statement}</p>
        </Disclosure>
      </div>

      {build.baselines && build.baselines.length > 0 && (
        <div className="case-baselines">
          <h3 className="section-title">What a simpler system would have said</h3>
          {build.baselines.map((b) => (
            <div className={`baseline-row ${b.agrees ? "agrees" : "differs"}`} key={b.key}>
              <div className="baseline-head">
                <span className="baseline-label">{b.label}</span>
                <span className={`pill baseline-verdict ${b.agrees ? "agrees" : "differs"}`}>
                  {b.agrees ? "Same answer" : "Different answer"}
                </span>
              </div>
              <p className="baseline-detail mono">{b.detail}</p>
              {/* Agreement is worth qualifying in two different ways,
                  and neither is a technicality. A baseline can agree by
                  a hair, or it can agree while its winner is 64 km from
                  the slick. Both are proximity landing on the right
                  answer rather than finding it, so the qualifier stays
                  beside the "same answer" it qualifies. */}
              {b.agrees && b.separation_km !== null && b.separation_km < 5 && (
                <p className="baseline-caveat">
                  It separates first from second by only {b.separation_km} km, so it reaches the same answer without
                  really distinguishing between them.
                </p>
              )}
              {b.agrees && b.winner_km !== null && b.winner_km > 20 && (
                <p className="baseline-caveat">
                  Its winner was {b.winner_km} km from the slick. Nothing was near the slick, so this agrees with us
                  without proximity doing any work.
                </p>
              )}
              <Disclosure label="What it assumes">
                <p>{b.assumes}</p>
              </Disclosure>
            </div>
          ))}
          <Disclosure label="Why compare against these">
            <p>
              Each of these is a real approach someone might take, run on this same case. The point is not that they are
              naive, it is what each one has to assume.
            </p>
          </Disclosure>
        </div>
      )}
    </section>
  );
}
