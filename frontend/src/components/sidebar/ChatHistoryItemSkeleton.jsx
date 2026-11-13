import "../../styles/sidebar.css";

function ChatHistoryItemSkeleton() {
  return (
    <div className="chat-history-item chat-history-item-skeleton" aria-label="Loading chat history">
      <div className="chat-history-skeleton-content">
        <div className="history-skeleton-line history-skeleton-title" />
        <div className="history-skeleton-line history-skeleton-meta" />
      </div>

      <div className="history-skeleton-action" />
    </div>
  );
}

export default ChatHistoryItemSkeleton;
