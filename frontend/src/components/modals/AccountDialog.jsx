import { useEffect, useId, useRef } from "react";
import { ArrowLeft, X } from "lucide-react";
import "../../styles/settings.css";
import "../../styles/account.css";

// The card shared by Profile and Change Password: the same look as Settings, with a
// back arrow (returns to Settings) and an X (closes it). Escape and a click outside
// the card close it too.
function AccountDialog({ title, onBack, onClose, children }) {
  const dialogRef = useRef(null);
  const headingRef = useRef(null);
  const backdropPointerRef = useRef(false);
  const titleId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    const trigger = document.activeElement;
    dialog.showModal();
    headingRef.current?.focus();
    return () => {
      dialog.close();
      if (trigger?.isConnected) trigger.focus();
    };
  }, []);

  return (
    <dialog
      ref={dialogRef}
      className="settings-dialog account-dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onPointerDown={(event) => {
        backdropPointerRef.current = event.target === event.currentTarget;
      }}
      onClick={(event) => {
        if (backdropPointerRef.current && event.target === event.currentTarget) onClose();
        backdropPointerRef.current = false;
      }}
    >
      <div className="settings-content">
        <button
          className="dialog-corner-button dialog-back"
          type="button"
          title="Back to Settings"
          aria-label="Back to Settings"
          onClick={onBack}
        >
          <ArrowLeft aria-hidden="true" />
        </button>
        <button
          className="dialog-corner-button dialog-close"
          type="button"
          title="Close"
          aria-label="Close"
          onClick={onClose}
        >
          <X aria-hidden="true" />
        </button>
        <h2 ref={headingRef} id={titleId} tabIndex={-1}>{title}</h2>
        {children}
      </div>
    </dialog>
  );
}

export default AccountDialog;
