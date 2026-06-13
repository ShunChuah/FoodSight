import { useState, useEffect, useRef } from "react";
import { PanelLeft, Plus, Search } from "lucide-react";
import Logo from "../../assets/foodsightLogo.png";
import DarkModeLogo from "../../assets/foodsightLogoDarkMode.png";
import ChatHistoryItem from "./ChatHistoryItem";
import ChatHistoryItemSkeleton from "./ChatHistoryItemSkeleton";
import GeneralDialog from "../modals/GeneralDialog";
import SidebarFooter from "./SidebarFooter";
import "../../styles/sidebar.css";

function Sidebar({
  chats,
  isLoadingChats = false,
  selectedChatId,
  setSelectedChatId,
  onNewChat,
  onRenameChat,
  onPinChat,
  onDeleteChat,
  onCloseSidebar,
  darkMode,
  setDarkMode,
  focusSearch,
  onSearchFocused,
}) {
  const [openMenuId, setOpenMenuId] = useState(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [chatPendingDeletion, setChatPendingDeletion] = useState(null);

  const searchInputRef = useRef(null);
  // Search filters by title only.
  const filteredChats = chats.filter((chat) =>
    chat.title.toLowerCase().includes(searchTerm.trim().toLowerCase()),
  );

  useEffect(() => {
    const handleClickOutside = (event) => {
      // Close the three-dot menu when the user clicks elsewhere.
      const clickedMenu = event.target.closest(".chat-menu");
      const clickedMoreButton = event.target.closest(".more-btn");

      if (!clickedMenu && !clickedMoreButton) {
        setOpenMenuId(null);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  useEffect(() => {
    // Used by the collapsed sidebar search button to focus this input.
    if (focusSearch && searchInputRef.current) {
      searchInputRef.current.focus();
      onSearchFocused?.();
    }
  }, [focusSearch, onSearchFocused]);

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <img
          src={darkMode ? DarkModeLogo : Logo}
          alt="FoodSight Logo"
          className="sidebar-logo"
        />

        <button
          className="close-sidebar-btn"
          type="button"
          onClick={onCloseSidebar}
        >
          <PanelLeft />
        </button>
      </div>

      <div className="history-title-row">
        <h2>History</h2>

        <button
          className="new-chat-btn"
          type="button"
          onClick={onNewChat}
        >
          <Plus strokeWidth={2.5} />
          <span>New Chat</span>
        </button>
      </div>

      <div className="search-chat-box">
        <Search strokeWidth={2.5} />
        <input
          ref={searchInputRef}
          type="text"
          placeholder="Search Chats"
          value={searchTerm}
          onChange={(event) => setSearchTerm(event.target.value)}
        />
      </div>

      <div className="chat-history-list">
        {isLoadingChats
          ? Array.from({ length: 6 }, (_, index) => (
              <ChatHistoryItemSkeleton key={index} />
            ))
          : filteredChats.map((chat) => (
              <ChatHistoryItem
                key={chat.id}
                title={chat.title}
                date={chat.date}
                time={chat.time}
                pinned={chat.pinned}
                selected={selectedChatId === chat.id}
                menuOpen={openMenuId === chat.id}
                onClick={() => {
                  // Selecting a history item loads that saved conversation.
                  setSelectedChatId(chat.id);
                  setOpenMenuId(null);
                }}
                onMoreClick={() => {
                  // Toggle the menu for only this chat item.
                  setOpenMenuId(openMenuId === chat.id ? null : chat.id);
                }}
                onRename={(title) => {
                  // ChatHistoryItem handles the inline input; parent saves to backend.
                  onRenameChat?.(chat.id, title);
                  setOpenMenuId(null);
                }}
                onPinToggle={() => {
                  // Send the opposite pinned value to the backend.
                  onPinChat?.(chat.id, !chat.pinned);
                  setOpenMenuId(null);
                }}
                onDelete={() => {
                  setChatPendingDeletion(chat);
                  setOpenMenuId(null);
                }}
              />
            ))}
      </div>

      <SidebarFooter darkMode={darkMode} setDarkMode={setDarkMode} />

      {chatPendingDeletion && (
        <GeneralDialog
          title="Delete Chat"
          description="Are you sure you want to delete this chat session? This action cannot be undone."
          secondaryLabel="Cancel"
          primaryLabel="Delete"
          onSecondary={() => setChatPendingDeletion(null)}
          onPrimary={() => {
            onDeleteChat?.(chatPendingDeletion.id);
            setChatPendingDeletion(null);
          }}
          onClose={() => setChatPendingDeletion(null)}
          destructive
        />
      )}
    </aside>
  );
}

export default Sidebar;
