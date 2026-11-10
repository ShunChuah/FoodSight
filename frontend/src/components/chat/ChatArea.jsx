import { useEffect, useRef, useState } from "react";
import WelcomeScreen from "./WelcomeScreen";
import ChatInput from "./ChatInput";
import AIResponseCard from "./AIResponseCard";
import ProcessingSteps from "./ProcessingSteps";
import FailureCard from "./FailureCard";
import ErrorBoundary from "../ErrorBoundary";
import UserQuestionBubble from "./UserQuestionBubble";
import AIExplanationPanel from "../explanation/AIExplanationPanel";
import { sendErrorText, submitChatQuery } from "../../services/submitChatQuery";
import { detailTabs, isGraphPending } from "../../services/detailsPresentation";
import { hasMapView } from "../../services/mapPresentation";
import { repliesFor } from "../../services/quickReplies";
import { failureText, questionBefore, withoutRetried } from "../../services/failures";
import "../../styles/chat.css";

const UNSHOWABLE_ANSWER = "This answer couldn't be shown. Your other messages are fine.";

function ChatArea({
  selectedChat,
  onPrepareQuery,
  onSendQuery,
  isSending = false,
  darkMode = false,
  showGraphEvidence = true,
  pendingQuery = "",
  streamingAnswer = "",
  processingStage = null,
  onStopQuery,
  retryingMessageId = null,
  onRetryQuery,
}) {
  const hasPendingQuery = Boolean(pendingQuery.trim());
  const messages = withoutRetried(selectedChat?.messages ?? [], retryingMessageId);
  const latestMessage = messages.at(-1);
  const hasSavedPendingUserMessage = messages.some(
    (message) =>
      message.type === "user" && message.text.trim() === pendingQuery.trim(),
  );
  // A message that could not be sent at all: its question and why, with Try again.
  const [failedSend, setFailedSend] = useState(null);
  const showWelcome =
    !hasPendingQuery && !failedSend && (!selectedChat || messages.length === 0);
  const resultRef = useRef(null);
  const [explanationMessageId, setExplanationMessageId] = useState(null);
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
    setFailedSend(null);
    try {
      await submitChatQuery(query, { prepare: onPrepareQuery, send: onSendQuery });
      return true;
    } catch (error) {
      setFailedSend({ query, message: sendErrorText(error) });
      return false;
    } finally {
      submissionInFlight.current = false;
    }
  };

  const retry = (messageId, question) => {
    if (!question) return;
    onRetryQuery?.(messageId);
    handleSubmit(question).then((sent) => {
      // Not sent: the failed answer comes back with its own Try again, not a second copy of the question.
      if (!sent) {
        onRetryQuery?.(null);
        setFailedSend(null);
      }
    });
  };

  useEffect(() => {
    const el = resultRef.current;
    if (!el) return;

    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
  }, [selectedChat?.id, selectedChat?.messages?.length, hasPendingQuery, streamingAnswer, failedSend]);

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
            {messages.map((message, index) => {
              const replies = message.type === "user" ? null : repliesFor(messages, index, pendingQuery);
              if (message.type === "assistant" && message.failure) {
                const latest = index === messages.length - 1;
                return (
                  <FailureCard
                    key={message.id}
                    message={failureText(message.failure)}
                    onRetry={latest ? () => retry(message.id, questionBefore(messages, index)) : undefined}
                    retryDisabled={isSending || hasPendingQuery}
                  />
                );
              }
              return message.type === "user" ? (
                <UserQuestionBubble key={message.id} text={message.text} />
              ) : (
                <ErrorBoundary key={message.id} fallback={<FailureCard message={UNSHOWABLE_ANSWER} />}>
                <AIResponseCard
                  answer={message.answer}
                  hasDetails={tabsFor(message).length > 0}
                  isExplanationOpen={explanationTabs.length > 0 && explanationMessageId === message.id}
                  onShowExplanation={() => setExplanationMessageId(message.id)}
                  quickReplies={replies.options}
                  selectedReply={replies.selected}
                  onQuickReply={handleSubmit}
                  repliesDisabled={isSending || hasPendingQuery}
                />
                </ErrorBoundary>
              );
            })}

            {hasPendingQuery && (
              <>
                {!hasSavedPendingUserMessage && (
                  <UserQuestionBubble text={pendingQuery} />
                )}
                {isSending && (streamingAnswer
                  ? <AIResponseCard answer={streamingAnswer} streaming />
                  : <ProcessingSteps stage={processingStage} onStop={onStopQuery} />)}
              </>
            )}

            {failedSend && !hasPendingQuery && (
              <>
                <UserQuestionBubble text={failedSend.query} />
                <FailureCard
                  message={failedSend.message}
                  onRetry={() => handleSubmit(failedSend.query)}
                  retryDisabled={isSending}
                />
              </>
            )}
          </div>
        )}

        <ChatInput
          onSendQuery={handleSubmit}
          showSuggestions={showWelcome}
          disabled={isSending || hasPendingQuery}
        />
      </section>

      {explanationTabs.length > 0 && (
        <ErrorBoundary resetKey={explanationMessageId} fallback={(
          <aside className="ai-explanation-panel">
            <FailureCard message="This view couldn't be shown. Close it and open it again." />
            <div className="response-actions">
              <button type="button" className="speak-action" onClick={() => setExplanationMessageId(null)}>Close</button>
            </div>
          </aside>
        )}>
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
        </ErrorBoundary>
      )}
    </main>
  );
}

export default ChatArea;
