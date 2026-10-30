import { useEffect, useRef, useState } from "react";
import Sidebar from "../components/sidebar/Sidebar";
import ClosedSidebar from "../components/sidebar/ClosedSidebar";
import ChatArea from "../components/chat/ChatArea";
import Settings from "../components/modals/Settings";
import { deleteChatBatch } from "../services/deleteChatBatch";
import { loadShowGraphEvidence, saveShowGraphEvidence } from "../services/detailsPresentation";
import { pendingGraphs, waitForGraph, withGraphEvidence } from "../services/pendingGraphs";
import {
  createChatHistory,
  deleteChatHistory,
  fetchChatHistories,
  fetchGraphEvidence,
  preflightChatMessage,
  renameChatHistory,
  sendChatMessage,
  updateChatPin,
} from "../api/chatApi";
import { fetchThemePreference, saveThemePreference } from "../api/preferencesApi";
import { useTheme } from "../context/ThemeContext.jsx";
import "../styles/dashboard.css";

function DashboardPage() {
  const { theme, setTheme } = useTheme();
  const darkMode = theme === "dark";
  const themeChangedRef = useRef(false);
  const setDarkMode = (next) => {
    const nextTheme = (typeof next === "function" ? next(darkMode) : next) ? "dark" : "light";
    themeChangedRef.current = true;
    setTheme(nextTheme);
    saveThemePreference(nextTheme).catch((error) => console.error("Failed to save theme", error));
  };
  const [showGraphEvidence, setShowGraphEvidence] = useState(loadShowGraphEvidence);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
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

  const getChatSortTime = (chat) => {
    const firstUserMessage = chat.messages?.find(
      (message) => message.type === "user",
    );

    return new Date(firstUserMessage?.createdAt ?? chat.createdAt).getTime();
  };

  const replaceChat = (savedChat) => {
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

  useEffect(() => {
    let ignore = false;

    async function loadChatHistories() {
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

  const pendingGraphKey = pendingGraphs(chats)
    .map(({ chatId, messageId }) => `${chatId}:${messageId}`)
    .join(",");
  useEffect(() => {
    if (!pendingGraphKey) return undefined;
    const controller = new AbortController();
    for (const key of pendingGraphKey.split(",")) {
      const [chatId, messageId] = key.split(":").map(Number);
      waitForGraph(() => fetchGraphEvidence(chatId, messageId), { signal: controller.signal })
        .then((result) => {
          if (result) setChats((previous) => withGraphEvidence(previous, chatId, messageId, result));
        });
    }
    return () => controller.abort();
  }, [pendingGraphKey]);

  // Apply the account's saved theme after login, unless the user already switched it on this page.
  useEffect(() => {
    let ignore = false;

    fetchThemePreference()
      .then((savedTheme) => {
        if (!ignore && savedTheme && !themeChangedRef.current) setTheme(savedTheme);
      })
      .catch((error) => console.error("Failed to load theme", error));

    return () => {
      ignore = true;
    };
  }, [setTheme]);

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
    if (!query.trim() || isSendingRef.current) return;

    isSendingRef.current = true;
    setIsSending(true);
    const chatId =
      preflightRef.current?.chatId
      ?? draftChatIdRef.current
      ?? selectedChatId;
    setPendingChatId(chatId);
    setPendingQuery(query);
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

      const savedChat = await sendPromise;
      replaceChat(savedChat);
      setSelectedChatId(savedChat.id);
    } catch (error) {
      console.error("Failed to save chat message", error);
      throw error;
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
    setSelectedChatId(null);
  };

  const handleSearchOpen = () => {
    setSidebarOpen(true);
    setShouldFocusSearch(true);
  };

  const handleSearchFocused = () => {
    setShouldFocusSearch(false);
  };

  const handleRenameChat = async (chatId, title) => {
    try {
      const savedChat = await renameChatHistory(chatId, title);
      replaceChat(savedChat);
    } catch (error) {
      console.error("Failed to rename chat history", error);
    }
  };

  const handlePinChat = async (chatId, pinned) => {
    try {
      const savedChat = await updateChatPin(chatId, pinned);
      replaceChat(savedChat);
    } catch (error) {
      console.error("Failed to update pinned chat", error);
    }
  };

  const handleDeleteChat = async (chatId) => {
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

  const handleClearHistory = async () => {
    if (isSending || isSendingRef.current || isLoadingChats) {
      throw new Error("Wait for the current chat operation to finish.");
    }
    const { deletedIds, failedIds } = await deleteChatBatch(
      chats.map((chat) => chat.id), deleteChatHistory,
    );
    const deleted = new Set(deletedIds);
    setChats((previous) => previous.filter((chat) => !deleted.has(chat.id)));
    setSelectedChatId((previous) => deleted.has(previous) ? null : previous);
    if (failedIds.length) throw new Error(`Failed to delete ${failedIds.length} chats.`);
  };

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
          onSettingsOpen={() => setSettingsOpen(true)}
        />
      ) : (
        <ClosedSidebar
          onOpenSidebar={() => setSidebarOpen(true)}
          onNewChat={handleNewChat}
          onSearchOpen={handleSearchOpen}
          onSettingsOpen={() => setSettingsOpen(true)}
        />
      )}

      <ChatArea
        key={selectedChat?.id ?? "new-chat"}
        selectedChat={selectedChat}
        onPrepareQuery={handlePrepareQuery}
        onSendQuery={handleSendQuery}
        isSending={isSending}
        darkMode={darkMode}
        showGraphEvidence={showGraphEvidence}
        pendingQuery={selectedOwnsPendingRequest ? pendingQuery : ""}
      />

      {settingsOpen && (
        <Settings
          darkMode={darkMode}
          onToggleDarkMode={() => setDarkMode((previous) => !previous)}
          showGraphEvidence={showGraphEvidence}
          onToggleGraphEvidence={() => {
            const next = !showGraphEvidence;
            setShowGraphEvidence(next);
            saveShowGraphEvidence(next);
          }}
          onClose={() => setSettingsOpen(false)}
          onClearHistory={handleClearHistory}
          hasChats={chats.length > 0}
          historyLoading={isLoadingChats}
          chatBusy={isSending}
        />
      )}
    </div>
  );
}

export default DashboardPage;
