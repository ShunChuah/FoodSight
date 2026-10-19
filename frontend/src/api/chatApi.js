import api from "./client";

export async function fetchChatHistories() {
  const response = await api.get("/chats");
  return response.data.chats;
}

export async function fetchChatHistory(chatId) {
  const response = await api.get(`/chats/${chatId}`);
  return response.data;
}

export async function createChatHistory(title) {
  const response = await api.post("/chats", { title });
  return response.data;
}

export async function sendChatMessage({
  chatId,
  message,
  location,
  locationPermissionDenied = false,
  preflight = null,
}) {
  const payload = {
    chat_id: chatId ?? null,
    message,
    location_name: locationPermissionDenied ? null : location?.name ?? null,
    latitude: locationPermissionDenied ? null : location?.latitude ?? null,
    longitude: locationPermissionDenied ? null : location?.longitude ?? null,
    location_permission_denied: locationPermissionDenied,
    preflight_token: preflight?.decisionToken ?? null,
  };

  // chatId is null for a new draft, so the backend creates the session on send.
  const response = await api.post("/chats/messages", payload);
  return response.data.chat;
}

export async function preflightChatMessage({ chatId, message }) {
  const response = await api.post("/chats/preflight", {
    chat_id: chatId ?? null,
    message,
  });
  return response.data;
}

export async function renameChatHistory(chatId, title) {
  const response = await api.patch(`/chats/${chatId}/title`, { title });
  return response.data;
}

export async function updateChatPin(chatId, pinned) {
  const response = await api.patch(`/chats/${chatId}/pin`, { pinned });
  return response.data;
}

export async function deleteChatHistory(chatId) {
  const response = await api.delete(`/chats/${chatId}`);
  return response.data;
}
