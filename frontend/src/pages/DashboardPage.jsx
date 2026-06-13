import { useEffect, useRef, useState } from "react";
import Sidebar from "../components/sidebar/Sidebar";
import ClosedSidebar from "../components/sidebar/ClosedSidebar";
import ChatArea from "../components/chat/ChatArea";
import {
  createChatHistory,
  deleteChatHistory,
  fetchChatHistory,
  fetchChatHistories,
  preflightChatMessage,
  renameChatHistory,
  sendChatMessage,
  updateChatPin,
} from "../api/chatApi";
import "../styles/dashboard.css";

function DashboardPage() {
  const [darkMode, setDarkMode] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [shouldFocusSearch, setShouldFocusSearch] = useState(false);
  const [chats, setChats] = useState([]);
  const [isLoadingChats, setIsLoadingChats] = useState(true);
  const [selectedChatId, setSelectedChatId] = useState(null);
  const [isSending, setIsSending] = useState(false);
  const [pendingQuery, setPendingQuery] = useState("");
  const [pendingChatId, setPendingChatId] = useState(null);
  const isSendingRef = useRef(false);
  const preflightRef = useRef(null);
  const draftChatIdRef = useRef(null);

  // Match backend ordering: pinned chats first, then first-query time descending.
  const getChatSortTime = (chat) => {
    const firstUserMessage = chat.messages?.find(
      (message) => message.type === "user",
    );

    return new Date(firstUserMessage?.createdAt ?? chat.createdAt).getTime();
  };

  const replaceChat = (savedChat) => {
    // Replace one updated chat in local state without reloading the whole list.
    setChats((prevChats) => {
      const nextChats = [
        savedChat,
        ...prevChats.filter((chat) => chat.id !== savedChat.id),
      ];

      return nextChats.sort((a, b) => {
        if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
        return getChatSortTime(b) - getChatSortTime(a);
      });
    });
  };

  const refreshGeneratedTitle = async (chatId, temporaryTitle) => {
    // Poll independently from Cypher generation so the sidebar title changes
    // within about one second of the background title being saved.
    for (let attempt = 0; attempt < 15; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      try {
        const refreshedChat = await fetchChatHistory(chatId);
        replaceChat(refreshedChat);
        if (refreshedChat.title !== temporaryTitle) return;
      } catch (error) {
        console.error("Failed to refresh generated chat title", error);
        return;
      }
    }
  };

  useEffect(() => {
    let ignore = false;

    async function loadChatHistories() {
      // Initial load from PostgreSQL when the dashboard opens.
      try {
        const savedChats = await fetchChatHistories();
        if (!ignore) {
          setChats(savedChats);
        }
      } catch (error) {
        console.error("Failed to load chat histories", error);
      } finally {
        if (!ignore) {
          setIsLoadingChats(false);
        }
      }
    }

    loadChatHistories();

    return () => {
      ignore = true;
    };
  }, []);

  const handlePrepareQuery = async (query) => {
    setIsSending(true);
    setPendingChatId(selectedChatId);
    setPendingQuery(query);

    let chatId = selectedChatId;
    if (chatId === null) {
      const draftChat = await createChatHistory("New Chat");
      draftChatIdRef.current = draftChat.id;
      chatId = draftChat.id;
      replaceChat(draftChat);
      setSelectedChatId(draftChat.id);
    }

    setPendingChatId(chatId);

    const decision = await preflightChatMessage({
      chatId,
      message: query,
    });
    preflightRef.current = { query, decision, chatId };
    return decision;
  };

  const handleSendQuery = async (
    query,
    location = null,
    locationPermissionDenied = false,
  ) => {
    // Sends the query to the backend, which saves user and assistant messages.
    if (!query.trim() || isSendingRef.current) return;

    isSendingRef.current = true;
    setIsSending(true);
    const chatId =
      preflightRef.current?.chatId
      ?? draftChatIdRef.current
      ?? selectedChatId;
    setPendingChatId(chatId);
    setPendingQuery(query);
    const isNewChat = draftChatIdRef.current === chatId;
    const temporaryTitle = isNewChat ? "New Chat" : "";
    try {
      const preflight =
        preflightRef.current?.query === query
          ? preflightRef.current.decision
          : null;
      const sendPromise = sendChatMessage({
        chatId,
        message: query,
        location,
        locationPermissionDenied,
        preflight,
      });

      if (isNewChat) {
        void refreshGeneratedTitle(chatId, temporaryTitle);
      }

      const savedChat = await sendPromise;
      replaceChat(savedChat);
      setSelectedChatId(savedChat.id);
    } catch (error) {
      console.error("Failed to save chat message", error);
    } finally {
      preflightRef.current = null;
      draftChatIdRef.current = null;
      isSendingRef.current = false;
      setIsSending(false);
      setPendingQuery("");
      setPendingChatId(null);
    }
  };

  const handleNewChat = () => {
    // Keeps this as an unsaved draft until the first query is sent.
    setSelectedChatId(null);
  };

  const handleSearchOpen = () => {
    // Reopen the sidebar and focus the search input.
    setSidebarOpen(true);
    setShouldFocusSearch(true);
  };

  const handleSearchFocused = () => {
    // Reset the one-time focus request after Sidebar handles it.
    setShouldFocusSearch(false);
  };

  const handleRenameChat = async (chatId, title) => {
    // Saves a new title, then replaces the updated chat in local state.
    try {
      const savedChat = await renameChatHistory(chatId, title);
      replaceChat(savedChat);
    } catch (error) {
      console.error("Failed to rename chat history", error);
    }
  };

  const handlePinChat = async (chatId, pinned) => {
    // Saves pinned state and re-sorts the local list.
    try {
      const savedChat = await updateChatPin(chatId, pinned);
      replaceChat(savedChat);
    } catch (error) {
      console.error("Failed to update pinned chat", error);
    }
  };

  const handleDeleteChat = async (chatId) => {
    // Deletes from backend first, then removes it from the sidebar state.
    try {
      await deleteChatHistory(chatId);
      setChats((prevChats) => prevChats.filter((chat) => chat.id !== chatId));
      if (selectedChatId === chatId) {
        setSelectedChatId(null);
      }
    } catch (error) {
      console.error("Failed to delete chat history", error);
    }
  };

  // Selected chat controls what conversation ChatArea renders.
  const selectedChat = chats.find((chat) => chat.id === selectedChatId);
  const selectedOwnsPendingRequest =
    pendingChatId === null
      ? selectedChatId === null && Boolean(pendingQuery.trim())
      : selectedChatId === pendingChatId;

  return (
    <div
      className="dashboard-page"
      data-theme={darkMode ? "dark" : "light"}
    >
      {sidebarOpen ? (
        <Sidebar
          chats={chats}
          isLoadingChats={isLoadingChats}
          selectedChatId={selectedChatId}
          setSelectedChatId={setSelectedChatId}
          darkMode={darkMode}
          setDarkMode={setDarkMode}
          onNewChat={handleNewChat}
          onRenameChat={handleRenameChat}
          onPinChat={handlePinChat}
          onDeleteChat={handleDeleteChat}
          focusSearch={shouldFocusSearch}
          onSearchFocused={handleSearchFocused}
          onCloseSidebar={() => setSidebarOpen(false)}
        />
      ) : (
        <ClosedSidebar
          onOpenSidebar={() => setSidebarOpen(true)}
          onNewChat={handleNewChat}
          onSearchOpen={handleSearchOpen}
        />
      )}

      <ChatArea
        key={selectedChat?.id ?? "new-chat"}
        selectedChat={selectedChat}
        onPrepareQuery={handlePrepareQuery}
        onSendQuery={handleSendQuery}
        isSending={isSending}
        darkMode={darkMode}
        pendingQuery={selectedOwnsPendingRequest ? pendingQuery : ""}
      />
    </div>
  );
}

export default DashboardPage;
