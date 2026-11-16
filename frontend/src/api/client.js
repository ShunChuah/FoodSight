import axios from "axios";

// The one client for every backend call (auth, chats, preferences); all live under /api/v1.
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1",
  withCredentials: true,
});

let onUnauthorized = () => {};

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler;
}

export function notifyUnauthorized() {
  onUnauthorized();
}

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) onUnauthorized();
    return Promise.reject(error);
  },
);

export function errorCode(error) {
  const detail = error.response?.data?.detail;
  return typeof detail === "string" ? detail : detail?.code;
}

export function errorReason(error) {
  return error.response?.data?.detail?.reason;
}
