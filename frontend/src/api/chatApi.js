import api, { notifyUnauthorized } from "./client";
import { readAnswerStream, streamError } from "../services/answerStream";

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
  onAnswer = null,
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

  // axios cannot read a streamed body.
  if (onAnswer && typeof fetch === "function") {
    return (await streamChatMessage(payload, onAnswer)).chat;
  }
  const response = await api.post("/chats/messages", payload);
  return response.data.chat;
}

async function streamChatMessage(payload, onAnswer) {
  const baseUrl = (api.defaults.baseURL ?? "").replace(/\/$/, "");
  const response = await fetch(`${baseUrl}/chats/messages/stream`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
    body: JSON.stringify(payload),
  });
  if (!response.ok || !response.body) {
    if (response.status === 401) notifyUnauthorized();
    const detail = await response.json().then((body) => body.detail).catch(() => undefined);
    throw streamError(response.status, detail);
  }
  return readAnswerStream(response, onAnswer);
}

export async function fetchGraphEvidence(chatId, messageId) {
  const response = await api.get(`/chats/${chatId}/messages/${messageId}/graph`);
  return response.data;
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
