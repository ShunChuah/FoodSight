import { Pencil, Pin, PinOff, Trash2 } from "lucide-react";
import "../../styles/sidebar.css";

function ChatHistoryMenu({ pinned, onRename, onPinToggle, onDelete, top, left }) {
  const menuStyle = {
    top: `${top}px`,
    left: `${left}px`,
  };

  return (
    <div className="chat-menu" style={menuStyle} onClick={(e) => e.stopPropagation()}>
      <button className="chat-menu-item" type="button" onClick={onRename}>
        <Pencil size={22} strokeWidth={2.5} />
        <span>Rename</span>
      </button>

      <button className="chat-menu-item" type="button" onClick={onPinToggle}>
        {pinned ? (
          <PinOff size={22} strokeWidth={2.5} />
        ) : (
          <Pin size={22} strokeWidth={2.5} />
        )}
        <span>{pinned ? "Unpin Chat" : "Pin Chat"}</span>
      </button>

      <button
        className="chat-menu-item delete"
        type="button"
        onClick={onDelete}
      >
        <Trash2 size={22} strokeWidth={2.5} />
        <span>Delete</span>
      </button>
    </div>
  );
}

export default ChatHistoryMenu;
