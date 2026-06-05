import "../../styles/chat.css";

function AIResponseSkeleton() {
  return (
    <div className="ai-response-card ai-response-skeleton" aria-label="Loading response">
      <div className="skeleton-line skeleton-line-long" />
      <div className="skeleton-line skeleton-line-long" />
      <div className="skeleton-line skeleton-line-long" />

      <div className="response-actions skeleton-actions">
        <div className="skeleton-button" />
        <div className="skeleton-button skeleton-button-secondary" />
      </div>
    </div>
  );
}

export default AIResponseSkeleton;
