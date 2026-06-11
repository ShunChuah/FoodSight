import { useEffect, useRef, useState } from "react";
import WelcomeScreen from "./WelcomeScreen";
import ChatInput from "./ChatInput";
import AIResponseCard from "./AIResponseCard";
import AIResponseSkeleton from "./AIResponseSkeleton";
import UserQuestionBubble from "./UserQuestionBubble";
import AIExplanationPanel from "../explanation/AIExplanationPanel";
import "../../styles/chat.css";

function ChatArea({
  selectedChat,
  onPrepareQuery,
  onSendQuery,
  isSending = false,
  pendingQuery = "",
}) {
  // No selected chat means the user is starting an unsaved draft conversation.
  const hasPendingQuery = Boolean(pendingQuery.trim());
  const messages = selectedChat?.messages ?? [];
  const showWelcome =
    !hasPendingQuery && (!selectedChat || messages.length === 0);
  const resultRef = useRef(null);
  const [explanationContext, setExplanationContext] = useState(null);

  // Scroll to bottom whenever the selected chat or its messages change
  useEffect(() => {
    const el = resultRef.current;
    if (!el) return;

    // Wait for DOM to update then scroll
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
  }, [selectedChat?.id, selectedChat?.messages?.length, hasPendingQuery]);

  return (
    <main
      className={`chat-area-with-panel ${
        explanationContext ? "has-explanation" : ""
      }`}
    >
      <section className="chat-card">
        {showWelcome ? (
          <WelcomeScreen />
        ) : (
          <div className="chat-result-area" ref={resultRef}>
            {messages.map((message) =>
              // User messages and assistant messages use different bubble/card UI.
              message.type === "user" ? (
                <UserQuestionBubble key={message.id} text={message.text} />
              ) : (
                <AIResponseCard
                  key={message.id}
                  answer={message.answer}
                  mapImage={message.mapImage}
                  isExplanationOpen={explanationContext?.messageId === message.id}
                  onShowExplanation={() =>
                    setExplanationContext({
                      messageId: message.id,
                      mapImage: message.mapImage,
                    })
                  }
                />
              ),
            )}

            {hasPendingQuery && (
              <>
                <UserQuestionBubble text={pendingQuery} />
                <AIResponseSkeleton />
              </>
            )}
          </div>
        )}

        <ChatInput
          onPrepareQuery={onPrepareQuery}
          onSendQuery={onSendQuery}
          showSuggestions={showWelcome}
          disabled={isSending}
        />
      </section>

      {explanationContext && (
        <AIExplanationPanel
          mapImage={explanationContext.mapImage}
          onClose={() => setExplanationContext(null)}
        />
      )}
    </main>
  );
}

export default ChatArea;
