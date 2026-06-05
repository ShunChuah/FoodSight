import { useEffect, useRef, useState } from "react";
import { Pin, PinOff, MoreVertical } from "lucide-react";
import "../../styles/sidebar.css";
import ChatHistoryMenu from "./ChatHistoryMenu";

function ChatHistoryItem({
  title,
  date,
  time,
  pinned = false,
  selected = false,
  menuOpen = false,
  onClick,
  onMoreClick,
  onRename,
  onPinToggle,
  onDelete,
}) {
  const moreButtonRef = useRef(null);
  const renameInputRef = useRef(null);
  const renameCancelledRef = useRef(false);
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0 });
  const [isRenaming, setIsRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState(title);

  useEffect(() => {
    // Position the menu near the three-dot button.
    if (menuOpen && moreButtonRef.current) {
      const rect = moreButtonRef.current.getBoundingClientRect();
      setMenuPos({
        top: rect.bottom + 16,
        left: rect.right - 50,
      });
    }
  }, [menuOpen]);

  useEffect(() => {
    // Focus and select the title text as soon as inline rename starts.
    if (isRenaming && renameInputRef.current) {
      renameInputRef.current.focus();
      renameInputRef.current.select();
    }
  }, [isRenaming]);

  const startRename = (event) => {
    // Switch from display title to inline input without selecting the chat row.
    event.stopPropagation();
    renameCancelledRef.current = false;
    setRenameValue(title);
    setIsRenaming(true);
    onMoreClick();
  };

  const commitRename = () => {
    // Blur saves the edited title; Escape sets this flag to cancel the blur save.
    if (renameCancelledRef.current) {
      renameCancelledRef.current = false;
      setIsRenaming(false);
      setRenameValue(title);
      return;
    }

    const nextTitle = renameValue.trim();
    setIsRenaming(false);

    if (nextTitle && nextTitle !== title) {
      onRename(nextTitle);
      return;
    }

    setRenameValue(title);
  };

  return (
    <div
      className={`chat-history-item ${selected ? "selected" : ""} ${menuOpen ? "menu-open" : ""}`}
      onClick={(event) => {
        if (!isRenaming) {
          onClick(event);
        }
      }}
    >
      <div className="chat-history-content">
        {isRenaming ? (
          <input
            ref={renameInputRef}
            className="chat-history-rename-input"
            type="text"
            value={renameValue}
            onClick={(event) => event.stopPropagation()}
            onChange={(event) => setRenameValue(event.target.value)}
            onBlur={commitRename}
            onKeyDown={(event) => {
              // Enter saves by blurring; Escape cancels by marking the ref.
              if (event.key === "Enter") {
                event.preventDefault();
                event.currentTarget.blur();
              }

              if (event.key === "Escape") {
                renameCancelledRef.current = true;
                event.currentTarget.blur();
              }
            }}
          />
        ) : (
          <h4>{title}</h4>
        )}
        <p>
          {date} &middot; {time}
        </p>
      </div>

      <div className="chat-history-actions">
        {pinned && (
          <button
            className="pin-toggle-btn"
            type="button"
            title="Unpin chat"
            onClick={(event) => {
              event.stopPropagation();
              onPinToggle();
            }}
          >
            <Pin size={26} strokeWidth={2.3} className="pin-normal-icon" />
            <PinOff size={26} strokeWidth={2.3} className="pin-unpin-icon" />
          </button>
        )}

        <button
          ref={moreButtonRef}
          className="more-btn"
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onMoreClick();
          }}
        >
          <MoreVertical size={20} strokeWidth={3} />
        </button>

        {menuOpen && (
          <ChatHistoryMenu
            pinned={pinned}
            onRename={startRename}
            onPinToggle={onPinToggle}
            onDelete={onDelete}
            top={menuPos.top}
            left={menuPos.left}
          />
        )}
      </div>
    </div>
  );
}

export default ChatHistoryItem;
