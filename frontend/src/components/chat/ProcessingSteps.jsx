import { Check, Circle, LoaderCircle } from "lucide-react";
import { processingSteps } from "../../services/processingSteps";
import "../../styles/chat.css";

const ICONS = {
  done: <Check className="processing-icon is-done" size={16} strokeWidth={2.5} aria-hidden="true" />,
  current: <LoaderCircle className="processing-icon is-current" size={18} strokeWidth={2.5} aria-hidden="true" />,
  waiting: <Circle className="processing-icon is-waiting" size={16} strokeWidth={2} aria-hidden="true" />,
};

function ProcessingSteps({ stage = null, onStop }) {
  const steps = processingSteps(stage);
  const current = steps.find((step) => step.state === "current");
  return (
    <div className="ai-response-card processing-card" role="status" aria-live="polite"
      aria-label={current ? current.label : "Preparing your answer"}>
      <ol className="processing-steps">
        {steps.map((step) => (
          <li key={step.key} className={`processing-step is-${step.state}`}>
            {ICONS[step.state]}
            <span className="processing-text">
              <span className="processing-label">{step.label}</span>
              {step.detail && <span className="processing-detail">({step.detail})</span>}
            </span>
          </li>
        ))}
      </ol>
      {onStop && (
        <button type="button" className="processing-stop" onClick={onStop}>
          Stop
        </button>
      )}
    </div>
  );
}

export default ProcessingSteps;
