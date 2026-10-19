import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

export function ProtectedRoute() {
  const { user, loading } = useAuth()
  if (loading) return null
  return user ? <Outlet /> : <Navigate to="/login" replace />
}

export function GuestRoute() {
  const { user, loading } = useAuth()
  if (loading) return null
  return user ? <Navigate to="/chat" replace /> : <Outlet />
}
