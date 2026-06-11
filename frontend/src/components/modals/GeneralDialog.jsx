import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import "../../styles/dialog.css";

function GeneralDialog({
  title,
  description,
  primaryLabel,
  secondaryLabel,
  onPrimary,
  onSecondary,
  onClose,
  destructive = false,
}) {
  const preferredButtonRef = useRef(null);
  const dismiss = onClose ?? onSecondary;

  useEffect(() => {
    preferredButtonRef.current?.focus();

    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        dismiss?.();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [dismiss]);

  return (
    <div
      className="general-dialog-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          dismiss?.();
        }
      }}
    >
      <div
        className="general-dialog"
        role={destructive ? "alertdialog" : "dialog"}
        aria-modal="true"
        aria-labelledby="general-dialog-title"
        aria-describedby="general-dialog-description"
      >
        {dismiss && (
          <button
            className="general-dialog-close"
            type="button"
            title="Close dialog"
            aria-label="Close dialog"
            onClick={dismiss}
          >
            <X aria-hidden="true" />
          </button>
        )}

        <h2 id="general-dialog-title">{title}</h2>
        <p id="general-dialog-description" className="general-dialog-description">
          {description}
        </p>

        <div
          className={`general-dialog-actions ${secondaryLabel ? "" : "single"}`}
        >
          {secondaryLabel && (
            <button
              ref={preferredButtonRef}
              className="general-dialog-secondary"
              type="button"
              onClick={onSecondary}
            >
              {secondaryLabel}
            </button>
          )}
          <button
            ref={secondaryLabel ? null : preferredButtonRef}
            className={`general-dialog-primary ${destructive ? "destructive" : ""}`}
            type="button"
            onClick={onPrimary}
          >
            {primaryLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export default GeneralDialog;
