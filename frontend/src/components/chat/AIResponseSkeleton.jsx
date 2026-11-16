import "../../styles/chat.css";

function AIResponseSkeleton({ embedded = false }) {
  return (
    <div className={embedded ? "ai-response-skeleton is-embedded" : "ai-response-card ai-response-skeleton"}
      aria-hidden={embedded || undefined} aria-label={embedded ? undefined : "Loading response"}>
      <div className="skeleton-line skeleton-line-long" />
      <div className="skeleton-line skeleton-line-long" />
      <div className="skeleton-line skeleton-line-long" />
    </div>
  );
}

export default AIResponseSkeleton;
