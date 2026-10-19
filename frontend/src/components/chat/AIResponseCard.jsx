import { Pause, Play, Sparkles, Volume2 } from "lucide-react";
import { parseAnswer } from "../../services/answerPresentation";
import useAnswerSpeech from "../../hooks/useAnswerSpeech";
import "../../styles/chat.css";

function formatInlineText(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);

  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      const value = part.slice(2, -2);
      const isPrice = /^(?:RM|[A-Z]{3}\s)\d+(?:\.\d+)?(?:[-–]\d+(?:\.\d+)?)?$/.test(value);
      return (
        <strong className={isPrice ? "ai-response-price" : undefined} key={`${part}-${index}`}>
          {value}
        </strong>
      );
    }

    return part;
  });
}

function FormattedAnswer({ answer }) {
  const blocks = parseAnswer(answer);

  return (
    <div className="ai-response-content">
      {blocks.map((block, index) => {
        if (block.type === "bullets") {
          return (
            <ul className="ai-response-list" key={`bullets-${index}`}>
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>{formatInlineText(item)}</li>
              ))}
            </ul>
          );
        }
        if (block.type === "list") {
          return (
            <ol className="ai-response-list" start={block.start} key={`list-${index}`}>
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>{formatInlineText(item)}</li>
              ))}
            </ol>
          );
        }

        return (
          <p className="ai-response-summary" key={`paragraph-${index}`}>
            {formatInlineText(block.text)}
          </p>
        );
      })}
    </div>
  );
}

function AIResponseCard({
  answer,
  hasDetails = false,
  onShowExplanation,
  isExplanationOpen = false,
}) {
  const speech = useAnswerSpeech(answer);
  const isSpeaking = speech.status === "speaking";
  const isPaused = speech.status === "paused";
  const speechLabel = isSpeaking ? "Pause Answer" : isPaused ? "Resume Answer" : "Speak Answer";
  const SpeechIcon = isSpeaking ? Pause : isPaused ? Play : Volume2;

  return (
    <div className="ai-response-card">
      <FormattedAnswer answer={answer} />

      <div className="response-actions">
        {hasDetails && (
          <button
            className="show-explanation-action"
            type="button"
            title="View Details"
            disabled={isExplanationOpen}
            onClick={() => onShowExplanation && onShowExplanation()}
          >
            <Sparkles />
            <span>View Details</span>
          </button>
        )}

        <button
          className={`speak-action${isSpeaking ? " selected" : ""}`}
          type="button"
          title={speech.notice || speechLabel}
          aria-label={isSpeaking ? "Speak Answer: pause" : isPaused ? "Speak Answer: resume" : "Speak Answer"}
          aria-describedby={speech.notice ? speech.noticeId : undefined}
          disabled={speech.disabled}
          onClick={speech.toggle}
        >
          <SpeechIcon aria-hidden="true" />
          <span>Speak Answer</span>
        </button>
      </div>
      {speech.notice && (
        <p className="speech-notice" id={speech.noticeId} role="status">
          {speech.notice}
        </p>
      )}
    </div>
  );
}

export default AIResponseCard;
