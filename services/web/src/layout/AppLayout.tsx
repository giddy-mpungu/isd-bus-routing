import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export function AppLayout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="brand">isd-bus-routing</span>
        {user && (
          <nav className="app-nav">
            <NavLink to="/schedule">Schedule</NavLink>
            <NavLink to="/setup">Setup</NavLink>
          </nav>
        )}
        {user && (
          <div className="user-info">
            <span>
              {user.full_name} ({user.role})
            </span>
            <button type="button" onClick={() => void logout()}>
              Log out
            </button>
          </div>
        )}
      </header>
      <div className="app-body">{children}</div>
    </div>
  )
}
