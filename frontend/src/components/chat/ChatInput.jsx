import { useEffect, useRef, useState } from "react";
import { CircleStop, ExternalLink, Mic, Send } from "lucide-react";
import "../../styles/chat.css";
import { quickQueries } from "../../../data/quickQueriesTemplate";

const MAX_MESSAGE_WORDS = 1000;
const MAX_MESSAGE_CHARACTERS = 5000;

function ChatInput({
  onSendQuery,
  quickReplies = [],
  showSuggestions,
  disabled = false,
}) {
  const queries = quickQueries;
  const [input, setInput] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [micPermissionTooltip, setMicPermissionTooltip] = useState("");
  const textareaRef = useRef(null);
  const recognitionRef = useRef(null);
  const isMessageEmpty = !input.trim();
  const wordCount = input.trim() ? input.trim().split(/\s+/).length : 0;
  const isMessageTooLong =
    wordCount > MAX_MESSAGE_WORDS || input.length > MAX_MESSAGE_CHARACTERS;
  const messageLimitNotice = wordCount > MAX_MESSAGE_WORDS
    ? "Your message is too long. Please keep it under 1,000 words."
    : "Your message is too long. Please keep it under 5,000 characters.";
  const sendDisabled =
    disabled
    || isRecording
    || isMessageEmpty
    || isMessageTooLong;

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, [input]);

  useEffect(
    () => () => {
      recognitionRef.current?.stop();
    },
    [],
  );

  const stopRecording = () => {
    recognitionRef.current?.stop();
    setIsRecording(false);
  };

  const handleSpeechToText = () => {
    if (isRecording) {
      stopRecording();
      return;
    }

    const SpeechRecognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setMicPermissionTooltip(
        "Speech recognition is not supported in this browser.",
      );
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .slice(event.resultIndex)
        .map((result) => result[0]?.transcript ?? "")
        .join(" ")
        .trim();

      if (!transcript) return;
      setInput((currentInput) =>
        [currentInput.trim(), transcript].filter(Boolean).join(" "),
      );
    };
    recognition.onerror = (event) => {
      console.error("Speech recognition failed", event.error);
      if (["not-allowed", "service-not-allowed"].includes(event.error)) {
        setMicPermissionTooltip("Please allow microphone access to use voice input.");
      }
      setIsRecording(false);
    };
    recognition.onend = () => {
      setIsRecording(false);
      recognitionRef.current = null;
    };

    try {
      recognition.start();
      recognitionRef.current = recognition;
      setMicPermissionTooltip("");
      setIsRecording(true);
    } catch (error) {
      console.error("Failed to start speech recognition", error);
      setMicPermissionTooltip("Please allow microphone access to use voice input.");
      recognitionRef.current = null;
      setIsRecording(false);
    }
  };

  const handleSuggestionClick = (query) => {
    // Put a quick query into the textarea so the user can edit before sending.
    stopRecording();
    setInput(query);
  };

  const handleSend = async () => {
    if (sendDisabled) return;
    const query = input.trim();
    setInput("");
    const sent = await onSendQuery(query);
    if (sent === false) setInput(query);
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

      {quickReplies.length > 0 && (
        <div className="quick-reply-actions" role="group" aria-label="Suggested replies">
          {quickReplies.map((reply) => (
            <button
              className="quick-reply-button"
              key={reply}
              type="button"
              disabled={disabled}
              onClick={() => onSendQuery(reply)}
            >
              {reply}
            </button>
          ))}
        </div>
      )}

      <div className="chat-input-box">
        <textarea
          ref={textareaRef}
          rows={1}
          placeholder={
            isRecording ? "Listening..." : "Ask me about F&B related questions..."
          }
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              handleSend();
            }
          }}
        />

        <div className="chat-input-actions">
          <span
            className={`voice-btn-wrapper ${
              micPermissionTooltip ? "has-tooltip" : ""
            }`}
            data-tooltip={micPermissionTooltip}
          >
            <button
              className={`voice-btn ${isRecording ? "recording" : ""}`}
              type="button"
              title={isRecording ? "Stop recording" : "Speech to text"}
              disabled={disabled && !isRecording}
              onClick={handleSpeechToText}
            >
              {isRecording ? <CircleStop /> : <Mic />}
            </button>
          </span>

          <span
            className={`send-btn-wrapper ${
              isMessageEmpty || isMessageTooLong ? "has-tooltip" : ""
            }`}
            data-tooltip={
              isMessageTooLong ? messageLimitNotice : "Please enter a message."
            }
          >
            <button
              className="send-btn"
              type="button"
              title={
                isMessageTooLong
                  ? messageLimitNotice
                  : isMessageEmpty
                    ? ""
                    : "Send"
              }
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
