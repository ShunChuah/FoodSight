import axios from "axios";

const chatApi = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
  withCredentials: true,
});

export default chatApi;

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  withCredentials: true,
});

let onUnauthorized = () => {};

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler;
}

for (const client of [chatApi, api]) {
  client.interceptors.response.use(
    (response) => response,
    (error) => {
      if (error.response?.status === 401) onUnauthorized();
      return Promise.reject(error);
    },
  );
}

export function errorCode(error) {
  const detail = error.response?.data?.detail;
  return typeof detail === "string" ? detail : detail?.code;
}

export function errorReason(error) {
  return error.response?.data?.detail?.reason;
}
