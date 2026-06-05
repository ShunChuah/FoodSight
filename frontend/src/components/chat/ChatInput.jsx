import { useEffect, useRef, useState } from "react";
import { AudioLines, Send, ExternalLink } from "lucide-react";
import "../../styles/chat.css";
import { quickQueries } from "../../../data/mockQuickQueries";

function ChatInput({ onSendQuery, showSuggestions, disabled = false }) {
  const queries = quickQueries;
  const [input, setInput] = useState("");
  const textareaRef = useRef(null);
  const isMessageEmpty = !input.trim();
  const sendDisabled = disabled || isMessageEmpty;

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, [input]);

  const handleSuggestionClick = (query) => {
    // Put a quick query into the textarea so the user can edit before sending.
    setInput(query);
  };

  const handleSend = () => {
    // Prevent empty sends and duplicate sends while the backend is processing.
    if (!input.trim() || disabled) return;

    onSendQuery(input);
    setInput("");
  };

  return (
    <div className="chat-bottom-section">
      {showSuggestions && (
        <div className="suggestion-box">
          <p>You might want to ask ...</p>

          <div className="suggestion-list">
            {queries.map((query, index) => (
              <button
                key={index}
                className="suggestion-btn"
                type="button"
                disabled={disabled}
                onClick={() => handleSuggestionClick(query)}
              >
                <span>{query}</span>
                <ExternalLink />
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="chat-input-box">
        <textarea
          ref={textareaRef}
          rows={1}
          placeholder="Ask me about F&B related questions..."
          value={input}
          disabled={disabled}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              handleSend();
            }
          }}
        />

        <div className="chat-input-actions">
          <button
            className="voice-btn"
            type="button"
            title="Text-to-Speech"
            disabled={disabled}
          >
            <AudioLines />
          </button>

          <span
            className={`send-btn-wrapper ${isMessageEmpty ? "is-empty" : ""}`}
            data-tooltip="Message is empty"
          >
            <button
              className="send-btn"
              type="button"
              title={isMessageEmpty ? "" : "Send"}
              onClick={handleSend}
              disabled={sendDisabled}
            >
              <Send />
            </button>
          </span>
        </div>
      </div>
    </div>
  );
}

export default ChatInput;
