import { useEffect, useRef, useState } from "react";
import WelcomeScreen from "./WelcomeScreen";
import ChatInput from "./ChatInput";
import AIResponseCard from "./AIResponseCard";
import AIResponseSkeleton from "./AIResponseSkeleton";
import UserQuestionBubble from "./UserQuestionBubble";
import AIExplanationPanel from "../explanation/AIExplanationPanel";
import { sendErrorText, submitChatQuery } from "../../services/submitChatQuery";
import { detailTabs, isGraphPending } from "../../services/detailsPresentation";
import { hasMapView } from "../../services/mapPresentation";
import "../../styles/chat.css";

function ChatArea({
  selectedChat,
  onPrepareQuery,
  onSendQuery,
  isSending = false,
  darkMode = false,
  showGraphEvidence = true,
  pendingQuery = "",
  streamingAnswer = "",
}) {
  const hasPendingQuery = Boolean(pendingQuery.trim());
  const messages = selectedChat?.messages ?? [];
  const latestMessage = messages.at(-1);
  const hasSavedPendingUserMessage = messages.some(
    (message) =>
      message.type === "user" && message.text.trim() === pendingQuery.trim(),
  );
  const showWelcome =
    !hasPendingQuery && (!selectedChat || messages.length === 0);
  const resultRef = useRef(null);
  const [explanationMessageId, setExplanationMessageId] = useState(null);
  const [sendError, setSendError] = useState("");
  const tabsFor = (message) => detailTabs(message, { showKnowledgeGraph: showGraphEvidence });
  const explanationMessage = messages.find((message) => message.id === explanationMessageId);
  const explanationTabs = explanationMessage ? tabsFor(explanationMessage) : [];
  const submissionInFlight = useRef(false);
  const wasSending = useRef(isSending);

  // A new answer with a map opens it straight away; answers already in a chat stay closed until asked for.
  useEffect(() => {
    const finished = wasSending.current && !isSending;
    wasSending.current = isSending;
    if (finished && latestMessage?.type === "assistant" && hasMapView(latestMessage.mapData, latestMessage.mapImage)) {
      setExplanationMessageId(latestMessage.id);
    }
  }, [isSending, latestMessage]);

  const handleSubmit = async (query) => {
    if (!query.trim() || isSending || submissionInFlight.current) return false;
    submissionInFlight.current = true;
    setSendError("");
    try {
      await submitChatQuery(query, { prepare: onPrepareQuery, send: onSendQuery });
      return true;
    } catch (error) {
      setSendError(sendErrorText(error));
      return false;
    } finally {
      submissionInFlight.current = false;
    }
  };

  useEffect(() => {
    const el = resultRef.current;
    if (!el) return;

    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
  }, [selectedChat?.id, selectedChat?.messages?.length, hasPendingQuery, streamingAnswer]);

  return (
    <main
      className={`chat-area-with-panel ${
        explanationTabs.length ? "has-explanation" : ""
      }`}
    >
      <section className="chat-card">
        {showWelcome ? (
          <WelcomeScreen darkMode={darkMode} />
        ) : (
          <div className="chat-result-area" ref={resultRef}>
            {messages.map((message) =>
              message.type === "user" ? (
                <UserQuestionBubble key={message.id} text={message.text} />
              ) : (
                <AIResponseCard
                  key={message.id}
                  answer={message.answer}
                  hasDetails={tabsFor(message).length > 0}
                  isExplanationOpen={explanationTabs.length > 0 && explanationMessageId === message.id}
                  onShowExplanation={() => setExplanationMessageId(message.id)}
                  quickReplies={message === latestMessage ? message.quickReplies ?? [] : []}
                  onQuickReply={handleSubmit}
                  repliesDisabled={isSending || hasPendingQuery}
                />
              ),
            )}

            {hasPendingQuery && (
              <>
                {!hasSavedPendingUserMessage && (
                  <UserQuestionBubble text={pendingQuery} />
                )}
                {isSending && (streamingAnswer
                  ? <AIResponseCard answer={streamingAnswer} streaming />
                  : <AIResponseSkeleton />)}
              </>
            )}
          </div>
        )}

        {sendError && <p className="chat-send-error" role="alert">{sendError}</p>}
        <ChatInput
          onSendQuery={handleSubmit}
          showSuggestions={showWelcome}
          disabled={isSending || hasPendingQuery}
        />
      </section>

      {explanationTabs.length > 0 && (
        <AIExplanationPanel
          key={explanationMessageId}
          tabs={explanationTabs}
          mapImage={explanationMessage.mapImage}
          mapData={explanationMessage.mapData}
          graphData={explanationMessage.graphData}
          graphPending={isGraphPending(explanationMessage)}
          darkMode={darkMode}
          onClose={() => setExplanationMessageId(null)}
        />
      )}
    </main>
  );
}

export default ChatArea;
