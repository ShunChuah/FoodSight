import { useEffect, useRef, useState } from "react";
import WelcomeScreen from "./WelcomeScreen";
import ChatInput from "./ChatInput";
import AIResponseCard from "./AIResponseCard";
import AIResponseSkeleton from "./AIResponseSkeleton";
import UserQuestionBubble from "./UserQuestionBubble";
import AIExplanationPanel from "../explanation/AIExplanationPanel";
import { submitChatQuery } from "../../services/submitChatQuery";
import { detailTabs } from "../../services/detailsPresentation";
import "../../styles/chat.css";

function ChatArea({
  selectedChat,
  onPrepareQuery,
  onSendQuery,
  isSending = false,
  darkMode = false,
  showGraphEvidence = true,
  pendingQuery = "",
}) {
  // No selected chat means the user is starting an unsaved draft conversation.
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
  const [explanationContext, setExplanationContext] = useState(null);
  const [sendError, setSendError] = useState("");
  const tabsFor = (message) => detailTabs(message, { showKnowledgeGraph: showGraphEvidence });
  // Re-checked on every render: turning graph evidence off can leave the open panel empty.
  const explanationTabs = explanationContext ? tabsFor(explanationContext.message) : [];
  const submissionInFlight = useRef(false);

  const handleSubmit = async (query) => {
    if (!query.trim() || isSending || submissionInFlight.current) return false;
    submissionInFlight.current = true;
    setSendError("");
    try {
      await submitChatQuery(query, { prepare: onPrepareQuery, send: onSendQuery });
      return true;
    } catch {
      setSendError("Your message couldn't be sent. Please try again.");
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
  }, [selectedChat?.id, selectedChat?.messages?.length, hasPendingQuery]);

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
                  isExplanationOpen={explanationTabs.length > 0 && explanationContext?.messageId === message.id}
                  onShowExplanation={() =>
                    setExplanationContext({ messageId: message.id, message })
                  }
                />
              ),
            )}

            {hasPendingQuery && (
              <>
                {!hasSavedPendingUserMessage && (
                  <UserQuestionBubble text={pendingQuery} />
                )}
                {isSending && <AIResponseSkeleton />}
              </>
            )}
          </div>
        )}

        {sendError && <p className="chat-send-error" role="alert">{sendError}</p>}
        <ChatInput
          onSendQuery={handleSubmit}
          quickReplies={latestMessage?.type === "assistant" ? latestMessage.quickReplies : []}
          showSuggestions={showWelcome}
          disabled={isSending || hasPendingQuery}
        />
      </section>

      {explanationTabs.length > 0 && (
        <AIExplanationPanel
          key={explanationContext.messageId}
          tabs={explanationTabs}
          mapImage={explanationContext.message.mapImage}
          mapData={explanationContext.message.mapData}
          graphData={explanationContext.message.graphData}
          darkMode={darkMode}
          onClose={() => setExplanationContext(null)}
        />
      )}
    </main>
  );
}

export default ChatArea;
