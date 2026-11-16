import { RotateCcw, TriangleAlert } from "lucide-react";
import "../../styles/chat.css";

// A failed answer in the same card as any answer: why it failed and, on the latest one, Try again.
function FailureCard({ message, onRetry, retryDisabled = false }) {
  return (
    <div className="ai-response-card failure-card" role="alert">
      <div className="failure-message">
        <TriangleAlert className="failure-icon" size={18} strokeWidth={2.2} aria-hidden="true" />
        <p className="ai-response-summary">{message}</p>
      </div>
      {onRetry && (
        <div className="response-actions">
          <button type="button" className="show-explanation-action failure-retry" onClick={onRetry}
            disabled={retryDisabled}>
            <RotateCcw aria-hidden="true" />
            Try again
          </button>
        </div>
      )}
    </div>
  );
}

export default FailureCard;
