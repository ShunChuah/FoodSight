import axios from "axios";

// One backend URL and client configuration for chat and map requests.
const chatApi = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
});

export default chatApi;

// Login and account requests (/api/v1). The session cookie is sent with each request.
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  withCredentials: true,
});

let onUnauthorized = () => {};

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler;
}

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) onUnauthorized();
    return Promise.reject(error);
  },
);

// The backend sends `detail` as either "SOME_CODE" or { code, reason }.
export function errorCode(error) {
  const detail = error.response?.data?.detail;
  return typeof detail === "string" ? detail : detail?.code;
}

export function errorReason(error) {
  return error.response?.data?.detail?.reason;
}
