import { useEffect, useId, useRef, useState } from "react";
import { Eraser, LockKeyhole, LogOut, Moon, Pencil, Waypoints } from "lucide-react";
import GeneralDialog from "./GeneralDialog";
import "../../styles/settings.css";

function Settings({
  darkMode,
  onToggleDarkMode,
  showGraphEvidence = true,
  onToggleGraphEvidence,
  onClose,
  onClearHistory,
  hasChats,
  historyLoading = false,
  chatBusy = false,
}) {
  const dialogRef = useRef(null);
  const headingRef = useRef(null);
  const clearButtonRef = useRef(null);
  const backdropPointerRef = useRef(false);
  const clearingRef = useRef(false);
  const wasConfirmingRef = useRef(false);
  const titleId = useId();
  const [confirmingClear, setConfirmingClear] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

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

  useEffect(() => {
    // When the confirmation closes, return focus to the menu (the button that opened it,
    // or the heading once there are no chats left to clear).
    if (wasConfirmingRef.current && !confirmingClear) {
      const button = clearButtonRef.current;
      (button && !button.disabled ? button : headingRef.current)?.focus();
    }
    wasConfirmingRef.current = confirmingClear;
  }, [confirmingClear]);

  const dismiss = () => {
    if (!clearingRef.current) onClose();
  };

  const closeConfirmation = () => {
    if (!clearingRef.current) setConfirmingClear(false);
  };

  const clearHistory = async () => {
    if (clearingRef.current || chatBusy || historyLoading) return;
    clearingRef.current = true;
    setIsClearing(true);
    setError("");
    try {
      await onClearHistory();
      setNotice("All chat history has been cleared.");
    } catch (failure) {
      console.error("Failed to clear chat history", failure);
      setError("Some chats couldn't be cleared. Please try again.");
    } finally {
      clearingRef.current = false;
      setIsClearing(false);
      setConfirmingClear(false);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      className="settings-dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        // Escape closes the confirmation first (GeneralDialog handles that), not Settings.
        if (!confirmingClear) dismiss();
      }}
      onPointerDown={(event) => {
        backdropPointerRef.current = event.target === event.currentTarget;
      }}
      onClick={(event) => {
        if (backdropPointerRef.current && event.target === event.currentTarget) dismiss();
        backdropPointerRef.current = false;
      }}
    >
      {/* While the confirmation is open, the menu behind it can't be focused or clicked. */}
      <div className="settings-content" inert={confirmingClear}>
        <h2 ref={headingRef} id={titleId} tabIndex={-1}>Settings</h2>

        <div className="settings-menu">
          <button className="settings-menu-item" type="button">
            <Pencil aria-hidden="true" />
            <span>Edit Profile</span>
          </button>
          <button className="settings-menu-item" type="button">
            <span className="settings-password-icon" aria-hidden="true"><LockKeyhole /></span>
            <span>Change Password</span>
          </button>
          <button
            ref={clearButtonRef}
            className="settings-menu-item"
            type="button"
            disabled={historyLoading || chatBusy || !hasChats}
            title={chatBusy ? "Wait for your answer to finish before clearing chats." : undefined}
            onClick={() => { setError(""); setNotice(""); setConfirmingClear(true); }}
          >
            <Eraser aria-hidden="true" />
            <span>Clear all chat history</span>
          </button>
          <button
            className="settings-menu-item"
            type="button"
            role="switch"
            aria-checked={darkMode}
            onClick={onToggleDarkMode}
          >
            <Moon aria-hidden="true" />
            <span>Dark Mode</span>
            <span className="settings-theme-switch" aria-hidden="true">
              <span className="settings-theme-thumb" />
            </span>
          </button>
          <button
            className="settings-menu-item"
            type="button"
            role="switch"
            aria-checked={showGraphEvidence}
            title="Show the Knowledge Graph Evidence tab in View Details"
            onClick={onToggleGraphEvidence}
          >
            <Waypoints aria-hidden="true" />
            <span>Knowledge Graph Evidence</span>
            <span className="settings-theme-switch" aria-hidden="true">
              <span className="settings-theme-thumb" />
            </span>
          </button>
          <button className="settings-menu-item settings-logout" type="button">
            <LogOut aria-hidden="true" />
            <span>Log Out</span>
          </button>
        </div>
        {notice && <p className="settings-notice" role="status">{notice}</p>}
        {error && <p className="settings-error" role="alert">{error}</p>}
      </div>

      {/* Rendered inside the modal <dialog> so it sits above it in the browser's top layer. */}
      {confirmingClear && (
        <GeneralDialog
          title="Clear Chat History"
          description="Are you sure you want to delete all saved chats and their messages? This action cannot be undone."
          secondaryLabel="Cancel"
          primaryLabel={isClearing ? "Clearing…" : "Clear All"}
          onSecondary={closeConfirmation}
          onPrimary={clearHistory}
          onClose={closeConfirmation}
          busy={isClearing}
          destructive
        />
      )}
    </dialog>
  );
}

export default Settings;
