import { useState } from "react";
import { ArrowLeft, ArrowRight, Info } from "lucide-react";
import { STAGES, type Stage } from "../lib/stages";
import type { DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
  stage: Stage;
  onSelect: (ordinal: number) => void;
}

// The three stages as a numbered rail, with the current stage's question
// and the bundle's own numbers that answer it.
//
// Every stage is clickable, not just the next one. A guided sequence
// that traps the presenter is worse than no sequence: during questions
// the room jumps straight to the drift or to the attribution, and having
// to step back through the acquisition to get there reads as a demo
// on rails rather than a tool.
//
// The answer leads with numbers because a sentence cannot be read from
// the back of a room. The same answer as a sentence sits behind the info
// button, generated from the same bundle.
export default function StageRail({ bundle, stage, onSelect }: Props) {
  const [showAnswer, setShowAnswer] = useState(false);
  const facts = stage.facts(bundle);
  const isLast = stage.ordinal === STAGES.length;

  return (
    <div className="stage-rail">
      <nav className="stage-steps" aria-label="Demo stages">
        {STAGES.map((s) => {
          const state = s.ordinal === stage.ordinal ? "current" : s.ordinal < stage.ordinal ? "done" : "ahead";
          return (
            <button
              key={s.key}
              className={`stage-step ${state}`}
              onClick={() => onSelect(s.ordinal)}
              aria-current={state === "current" ? "step" : undefined}
              title={`${s.question} (key ${s.ordinal})`}
            >
              <span className="stage-step-ordinal mono">{s.ordinal}</span>
              <span className="stage-step-label">{s.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="stage-copy">
        <h2 className="stage-question">{stage.question}</h2>
        <div className="stage-facts">
          {facts.map((f) => (
            <span className="stage-fact" key={f.label}>
              <span className="stage-fact-value mono">{f.value}</span>
              <span className="stage-fact-label">{f.label}</span>
            </span>
          ))}
          <button
            type="button"
            className={`stage-answer-toggle${showAnswer ? " active" : ""}`}
            onClick={() => setShowAnswer((v) => !v)}
            aria-expanded={showAnswer}
            title="Read the answer as a sentence"
          >
            <Info size={16} strokeWidth={1.8} aria-hidden="true" />
          </button>
        </div>
        {showAnswer && <p className="stage-answer">{stage.answer(bundle)}</p>}
      </div>

      <div className="stage-nav">
        <button
          className="stage-nav-button"
          onClick={() => onSelect(stage.ordinal - 1)}
          disabled={stage.ordinal === 1}
          aria-label="Previous stage"
          title="Previous stage (left arrow)"
        >
          <ArrowLeft size={16} strokeWidth={1.8} aria-hidden="true" />
        </button>
        <button
          className="stage-nav-button primary"
          onClick={() => onSelect(stage.ordinal + 1)}
          disabled={isLast}
          title="Next stage (right arrow)"
        >
          {isLast ? "End" : `Next: ${STAGES[stage.ordinal].label}`}
          {!isLast && <ArrowRight size={16} strokeWidth={1.8} aria-hidden="true" />}
        </button>
      </div>
    </div>
  );
}
