import axios from "axios";

// One backend URL and client configuration for chat and map requests.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
});

export default api;
