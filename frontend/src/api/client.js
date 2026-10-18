import axios from 'axios'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  withCredentials: true,
})

let onUnauthorized = () => {}

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler
}

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) onUnauthorized()
    return Promise.reject(error)
  },
)

// The backend sends `detail` as either "SOME_CODE" or { code, reason }.
export function errorCode(error) {
  const detail = error.response?.data?.detail
  return typeof detail === 'string' ? detail : detail?.code
}

export function errorReason(error) {
  return error.response?.data?.detail?.reason
}
