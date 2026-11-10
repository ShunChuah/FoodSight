import { useEffect } from "react";
import { TriangleAlert, X } from "lucide-react";
import "../styles/notice.css";

const SHOWN_MS = 5000;

// A short message for an action that failed (rename, pin, delete), closed by the user or after a few seconds.
function Notice({ message, onClose }) {
  useEffect(() => {
    if (!message) return undefined;
    const timer = setTimeout(onClose, SHOWN_MS);
    return () => clearTimeout(timer);
  }, [message, onClose]);

  if (!message) return null;
  return (
    <div className="app-notice" role="alert">
      <TriangleAlert className="app-notice-icon" size={18} strokeWidth={2.2} aria-hidden="true" />
      <p>{message}</p>
      <button type="button" className="app-notice-close" onClick={onClose} aria-label="Close message">
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  );
}

export default Notice;
