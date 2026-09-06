import { STAGES, type Stage } from "../lib/stages";
import type { DemoBundle } from "../types";

interface Props {
  bundle: DemoBundle;
  stage: Stage;
  onSelect: (ordinal: number) => void;
}

// The three stages as a numbered rail, with the current stage's question
// and its answer underneath.
//
// Every stage is clickable, not just the next one. A guided sequence
// that traps the presenter is worse than no sequence: during questions
// the room jumps straight to the drift or to the attribution, and having
// to step back through the acquisition to get there reads as a demo
// on rails rather than a tool.
export default function StageRail({ bundle, stage, onSelect }: Props) {
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
              title={s.question}
            >
              <span className="stage-step-ordinal mono">{s.ordinal}</span>
              <span className="stage-step-label">{s.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="stage-copy">
        <h2 className="stage-question">{stage.question}</h2>
        <p className="stage-answer">{stage.answer(bundle)}</p>
      </div>

      <div className="stage-nav">
        <button
          className="stage-nav-button"
          onClick={() => onSelect(stage.ordinal - 1)}
          disabled={stage.ordinal === 1}
        >
          Back
        </button>
        <button
          className="stage-nav-button primary"
          onClick={() => onSelect(stage.ordinal + 1)}
          disabled={stage.ordinal === STAGES.length}
        >
          {stage.ordinal === STAGES.length ? "End of sequence" : `Next: ${STAGES[stage.ordinal].label}`}
        </button>
      </div>
    </div>
  );
}
