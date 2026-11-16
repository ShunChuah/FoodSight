import { api, notifyUnauthorized } from "./client";
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
  onStage = null,
  signal = undefined,
  retryOf = null,
  onStarted = null,
}) {
  const payload = {
    chat_id: chatId ?? null,
    message,
    location_name: locationPermissionDenied ? null : location?.name ?? null,
    latitude: locationPermissionDenied ? null : location?.latitude ?? null,
    longitude: locationPermissionDenied ? null : location?.longitude ?? null,
    location_permission_denied: locationPermissionDenied,
    preflight_token: preflight?.decisionToken ?? null,
    retry_of: retryOf,
  };

  // axios cannot read a streamed body.
  if (onAnswer && typeof fetch === "function") {
    return (await streamChatMessage(payload, onAnswer, onStage, signal, onStarted)).chat;
  }
  const response = await api.post("/chats/messages", payload);
  return response.data.chat;
}

// Aborting the signal (Stop) closes the stream, and the server then stops before its next model call.
async function streamChatMessage(payload, onAnswer, onStage, signal, onStarted) {
  const baseUrl = (api.defaults.baseURL ?? "").replace(/\/$/, "");
  const response = await fetch(`${baseUrl}/chats/messages/stream`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok || !response.body) {
    if (response.status === 401) notifyUnauthorized();
    const detail = await response.json().then((body) => body.detail).catch(() => undefined);
    throw streamError(response.status, detail);
  }
  return readAnswerStream(response, onAnswer, onStage, onStarted);
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

// Stop: the server keeps the question with an interrupted answer and sends the chat back on the open stream.
export async function stopChatTurn(turnId) {
  await api.post(`/chats/turns/${turnId}/stop`);
}

// The map tour's words tied to the question, written by the model once per answer; steps it can't cover are left out.
export async function fetchTourScript(chatId, messageId, steps) {
  const response = await api.post(`/chats/${chatId}/messages/${messageId}/tour`, { steps }, { timeout: 35000 });
  return response.data?.steps ?? {};
}

// The map tour's spoken line as MP3; the server makes it once and keeps it.
export async function fetchNarration(text) {
  const response = await api.post("/narration", { text }, { responseType: "blob", timeout: 25000 });
  return response.data;
}

export async function deleteChatHistory(chatId) {
  const response = await api.delete(`/chats/${chatId}`);
  return response.data;
}
