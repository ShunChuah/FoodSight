import { useEffect, useRef, useState } from "react";
import { AudioLines, ExternalLink, Send } from "lucide-react";
import "../../styles/chat.css";
import { quickQueries } from "../../../data/quickQueriesTemplate";
import GeneralDialog from "../modals/GeneralDialog";

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
  const [locationDialog, setLocationDialog] = useState(null);
  const [pendingLocationQuery, setPendingLocationQuery] = useState("");
  const [isResolvingLocation, setIsResolvingLocation] = useState(false);
  const textareaRef = useRef(null);
  const isMessageEmpty = !input.trim();
  const wordCount = input.trim() ? input.trim().split(/\s+/).length : 0;
  const isMessageTooLong =
    wordCount > MAX_MESSAGE_WORDS || input.length > MAX_MESSAGE_CHARACTERS;
  const sendDisabled =
    disabled || isResolvingLocation || isMessageEmpty || isMessageTooLong;

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, [input]);

  useEffect(() => {
    // The completed backend response is authoritative. Clear any stale local
    // geolocation lock left by browser permission callbacks or component timing.
    if (!disabled) {
      setIsResolvingLocation(false);
    }
  }, [disabled]);

  const handleSuggestionClick = (query) => {
    // Put a quick query into the textarea so the user can edit before sending.
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
    setLocationDialog(null);
    setPendingLocationQuery("");
    await onSendQuery(query, location, locationPermissionDenied);
  };

  const requestBrowserLocation = async (queryOverride = "") => {
    const query = (queryOverride || pendingLocationQuery).trim();
    if (!query) {
      setIsResolvingLocation(false);
      return;
    }

    if (!navigator.geolocation) {
      await submitQuery(query, null, true);
      return;
    }

    setLocationDialog(null);
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

    if (!navigator.permissions?.query) {
      setPendingLocationQuery(query);
      setLocationDialog("permission");
      return;
    }

    try {
      const permission = await navigator.permissions.query({
        name: "geolocation",
      });

      if (permission.state === "granted") {
        await requestBrowserLocation(query);
        return;
      }

      if (permission.state === "denied") {
        await submitQuery(query, null, true);
        return;
      }
    } catch (error) {
      console.error("Failed to check location permission", error);
    }

    setPendingLocationQuery(query);
    setLocationDialog("permission");
  };

  const cancelLocationPermission = async () => {
    const query = pendingLocationQuery.trim();
    setLocationDialog(null);
    setPendingLocationQuery("");
    setIsResolvingLocation(false);

    if (query) {
      await submitQuery(query, null, true);
    }
  };

  const handleSend = async () => {
    // Prevent empty sends and duplicate sends while the backend is processing.
    if (
      !input.trim()
      || disabled
      || isResolvingLocation
      || isMessageTooLong
    ) {
      return;
    }

    const query = input.trim();
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
          placeholder="Ask me about F&B related questions..."
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
          <button
            className="voice-btn"
            type="button"
            title="Text-to-Speech"
            disabled={disabled}
          >
            <AudioLines />
          </button>

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

      {locationDialog && (
        <GeneralDialog
          title="Enable Location Permission"
          description="Foodsight will need your location to give you better experience."
          secondaryLabel="Cancel"
          primaryLabel="Use Current Location"
          onSecondary={cancelLocationPermission}
          onPrimary={() => requestBrowserLocation()}
          onClose={cancelLocationPermission}
        />
      )}
    </div>
  );
}

export default ChatInput;
