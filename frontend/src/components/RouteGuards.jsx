import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { homeFor } from '../roles.js'

// Any logged-in account, admin or not.
export function ProtectedRoute() {
  const { user, loading } = useAuth()
  if (loading) return null
  return user ? <Outlet /> : <Navigate to="/login" replace />
}

// Normal users only (the chat): an admin is sent to the admin pages instead.
export function UserRoute() {
  const { user, loading } = useAuth()
  if (loading) return null
  if (!user) return <Navigate to="/login" replace />
  return user.is_superuser ? <Navigate to={homeFor(user)} replace /> : <Outlet />
}

// Admin pages (business submissions, and the pipeline review pages): only accounts with is_superuser.
// The pipeline review pages' backend checks it too; business submissions have no backend yet.
export function AdminRoute() {
  const { user, loading } = useAuth()
  if (loading) return null
  if (!user) return <Navigate to="/login" replace />
  return user.is_superuser ? <Outlet /> : <Navigate to={homeFor(user)} replace />
}

export function GuestRoute() {
  const { user, loading } = useAuth()
  if (loading) return null
  return user ? <Navigate to={homeFor(user)} replace /> : <Outlet />
}
