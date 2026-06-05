import axios from "axios";

// Shared Axios client for every frontend request to the FastAPI backend.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
});

export async function fetchChatHistories() {
  // Loads saved chat sessions for the sidebar.
  const response = await api.get("/chats");
  return response.data.chats;
}

export async function sendChatMessage({ chatId, message }) {
  // chatId is null for a new draft, so the backend creates the session on send.
  const response = await api.post("/chats/messages", {
    chat_id: chatId ?? null,
    message,
  });
  return response.data.chat;
}

export async function renameChatHistory(chatId, title) {
  // Saves inline title edits to PostgreSQL through the backend.
  const response = await api.patch(`/chats/${chatId}/title`, { title });
  return response.data;
}

export async function updateChatPin(chatId, pinned) {
  // Persists pinned state so pinned chats remain on top after refresh.
  const response = await api.patch(`/chats/${chatId}/pin`, { pinned });
  return response.data;
}

export async function deleteChatHistory(chatId) {
  // Removes the chat session and its messages.
  const response = await api.delete(`/chats/${chatId}`);
  return response.data;
}
