import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import type { Role } from '../api/types'
import { useAuth } from './AuthContext'

export function ProtectedRoute({
  allowedRoles,
  children,
}: {
  allowedRoles: Role[]
  children: ReactNode
}) {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return <p>Loading…</p>
  }
  if (!user) {
    return <Navigate to="/login" replace />
  }
  if (!allowedRoles.includes(user.role)) {
    // A working "not authorized" state, not a broken page — this
    // slice's console is only built for dispatcher/transportation_admin
    // (docs/architecture.md), and the backend already enforces the
    // same boundary on every endpoint this page calls.
    return (
      <p role="alert">
        Your account role ("{user.role}") isn't authorized to use the dispatcher console.
      </p>
    )
  }
  return <>{children}</>
}
