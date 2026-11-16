import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

export function ProtectedRoute() {
  const { user, loading } = useAuth()
  if (loading) return null
  return user ? <Outlet /> : <Navigate to="/login" replace />
}

// Admin pages (business submissions, and the pipeline review page): only accounts with is_superuser.
// The pipeline review page's backend checks it too; business submissions have no backend yet.
export function AdminRoute() {
  const { user, loading } = useAuth()
  if (loading) return null
  if (!user) return <Navigate to="/login" replace />
  return user.is_superuser ? <Outlet /> : <Navigate to="/chat" replace />
}

export function GuestRoute() {
  const { user, loading } = useAuth()
  if (loading) return null
  return user ? <Navigate to="/chat" replace /> : <Outlet />
}
