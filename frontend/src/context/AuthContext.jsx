import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api, setUnauthorizedHandler } from '../api/client.js'

const AuthContext = createContext(null)

// Marks that this browser had a session, so a never-logged-in visitor is not told their session expired.
const SIGNED_IN_KEY = 'foodsight-signed-in'
const SESSION_EXPIRED = 'Session expired, please log in again.'
const SESSION_UNVERIFIED = 'We could not verify your session. Please log in again.'
const SESSION_CHECK_MS = 60_000

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState(null)

  const endSession = useCallback((message) => {
    const wasSignedIn = localStorage.getItem(SIGNED_IN_KEY)
    localStorage.removeItem(SIGNED_IN_KEY)
    setUser(null)
    if (wasSignedIn) setNotice(message)
  }, [])

  // The session cookie is httpOnly, so asking the backend is the only way to know who is logged in.
  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get('/users/me')
      localStorage.setItem(SIGNED_IN_KEY, '1')
      setUser(data)
      return data
    } catch (error) {
      endSession(error.response?.status === 401 ? SESSION_EXPIRED : SESSION_UNVERIFIED)
      return null
    } finally {
      setLoading(false)
    }
  }, [endSession])

  useEffect(() => {
    setUnauthorizedHandler(() => endSession(SESSION_EXPIRED))
    refresh()
  }, [endSession, refresh])

  const loggedIn = Boolean(user)
  useEffect(() => {
    if (!loggedIn) return
    const check = () => document.visibilityState === 'visible' && refresh()
    const timer = setInterval(check, SESSION_CHECK_MS)
    document.addEventListener('visibilitychange', check)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', check)
    }
  }, [loggedIn, refresh])

  const logout = async () => {
    localStorage.removeItem(SIGNED_IN_KEY)
    try {
      await api.post('/auth/logout')
    } catch {
      // Already logged out on the server; the local state is cleared either way.
    }
    setUser(null)
  }

  const clearNotice = useCallback(() => setNotice(null), [])

  return (
    <AuthContext.Provider value={{ user, loading, notice, clearNotice, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
