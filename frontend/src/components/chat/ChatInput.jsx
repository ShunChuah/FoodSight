import { useEffect, useRef, useState } from "react";
import { CircleStop, ExternalLink, Mic, Send } from "lucide-react";
import "../../styles/chat.css";
import { quickQueries } from "../../../data/quickQueriesTemplate";

const MAX_MESSAGE_WORDS = 1000;
const MAX_MESSAGE_CHARACTERS = 5000;

function ChatInput({
  onPrepareQuery,
  onSendQuery,
  showSuggestions,
  disabled = false,
}) {
  const GEOLOCATION_PERMISSION_DENIED = 1;
  const queries = quickQueries;
  const [input, setInput] = useState("");
  const [isResolvingLocation, setIsResolvingLocation] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [micPermissionTooltip, setMicPermissionTooltip] = useState("");
  const textareaRef = useRef(null);
  const recognitionRef = useRef(null);
  const isMessageEmpty = !input.trim();
  const wordCount = input.trim() ? input.trim().split(/\s+/).length : 0;
  const isMessageTooLong =
    wordCount > MAX_MESSAGE_WORDS || input.length > MAX_MESSAGE_CHARACTERS;
  const sendDisabled =
    disabled
    || isResolvingLocation
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
        setMicPermissionTooltip("Enable microphone permission to use voice input.");
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
      setMicPermissionTooltip("Enable microphone permission to use voice input.");
      recognitionRef.current = null;
      setIsRecording(false);
    }
  };

  const handleSuggestionClick = (query) => {
    // Put a quick query into the textarea so the user can edit before sending.
    stopRecording();
    setInput(query);
  };

  const submitQuery = async (
    query,
    location,
    locationPermissionDenied = false,
  ) => {
    // Location preparation is complete once the message is ready to submit.
    // The parent `disabled` prop exclusively owns the backend-generation lock.
    setIsResolvingLocation(false);
    setInput("");
    await onSendQuery(query, location, locationPermissionDenied);
  };

  const requestBrowserLocation = async (queryOverride) => {
    const query = queryOverride.trim();
    if (!query) {
      setIsResolvingLocation(false);
      return;
    }

    if (!navigator.geolocation) {
      await submitQuery(query, null, true);
      return;
    }

    setIsResolvingLocation(true);
    let position;
    try {
      position = await new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: false,
          timeout: 30000,
          maximumAge: 300000,
        });
      });
    } catch (error) {
      console.error("Failed to get browser location", error);
      setIsResolvingLocation(false);
      await submitQuery(
        query,
        null,
        error?.code === GEOLOCATION_PERMISSION_DENIED,
      );
      return;
    }

    setIsResolvingLocation(false);
    await submitQuery(query, {
      source: "browser",
      latitude: position.coords.latitude,
      longitude: position.coords.longitude,
    });
  };

  const resolveLocationPermission = async (query) => {
    if (!navigator.geolocation) {
      await submitQuery(query, null, true);
      return;
    }

    try {
      const permission = navigator.permissions?.query
        ? await navigator.permissions.query({ name: "geolocation" })
        : null;
      if (permission?.state === "denied") {
        await submitQuery(query, null, true);
        return;
      }
    } catch (error) {
      console.error("Failed to check location permission", error);
    }

    await requestBrowserLocation(query);
  };

  const handleSend = async () => {
    // Prevent empty sends and duplicate sends while the backend is processing.
    if (
      !input.trim()
      || disabled
      || isResolvingLocation
      || isRecording
      || isMessageTooLong
    ) {
      return;
    }

    const query = input.trim();
    setInput("");
    setIsResolvingLocation(true);
    try {
      const preflight = await onPrepareQuery(query);
      if (!preflight.isFnb || !preflight.locationRequired) {
        const location = preflight.detectedLocation
          ? { source: "query", name: preflight.detectedLocation }
          : null;
        setIsResolvingLocation(false);
        await submitQuery(query, location);
        return;
      }

      await resolveLocationPermission(query);
    } catch (error) {
      console.error("Failed to prepare chat query", error);
      await resolveLocationPermission(query);
    } finally {
      setIsResolvingLocation(false);
    }
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
              isMessageTooLong ? "Text is too long" : "Message is empty"
            }
          >
            <button
              className="send-btn"
              type="button"
              title={
                isResolvingLocation
                  ? "Getting location"
                  : isMessageTooLong
                    ? "Text too long"
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
