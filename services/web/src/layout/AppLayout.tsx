import { useEffect, useRef, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

// Each page's name for the browser tab and screen readers (WCAG 2.4.2).
const PAGE_TITLES: Record<string, string> = {
  '/login': 'Sign in',
  '/forgot-password': 'Forgot your password',
  '/reset-password': 'Choose a password',
  '/email-preferences': 'Bus time emails',
  '/account': 'Account',
  '/schedule': 'Schedule',
  '/field-trips': 'Field trips',
  '/templates': 'Recurring templates',
  '/reports': 'Reports',
  '/setup': 'Setup',
  '/users': 'Users',
  '/driver': 'My day',
  '/family': 'My family',
  '/school': 'My school',
}

export function AppLayout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const { pathname } = useLocation()
  const mainRef = useRef<HTMLDivElement | null>(null)
  const firstRender = useRef(true)

  useEffect(() => {
    const title = PAGE_TITLES[pathname]
    document.title = title ? `${title} · isd-bus-routing` : 'isd-bus-routing'
    // After moving to another page, start screen readers and keyboards at
    // its content rather than wherever focus was (the link just pressed).
    if (firstRender.current) {
      firstRender.current = false
      return
    }
    mainRef.current?.focus()
  }, [pathname])

  return (
    <div className="app-shell">
      {/* WCAG 2.4.1: past the menu straight to the page. */}
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className="app-header">
        <span className="brand">isd-bus-routing</span>
        {user && (user.role === 'dispatcher' || user.role === 'transportation_admin') && (
          <nav className="app-nav" aria-label="Main">
            <NavLink to="/schedule">Schedule</NavLink>
            <NavLink to="/field-trips">Field Trips</NavLink>
            <NavLink to="/templates">Templates</NavLink>
            <NavLink to="/reports">Reports</NavLink>
            <NavLink to="/setup">Setup</NavLink>
            {user.role === 'transportation_admin' && <NavLink to="/users">Users</NavLink>}
          </nav>
        )}
        {user && user.role === 'driver' && (
          <nav className="app-nav" aria-label="Main">
            <NavLink to="/driver">My day</NavLink>
          </nav>
        )}
        {user && (user.role === 'student' || user.role === 'parent') && (
          <nav className="app-nav" aria-label="Main">
            <NavLink to="/family">My Family</NavLink>
          </nav>
        )}
        {user && user.role === 'school_admin' && (
          <nav className="app-nav" aria-label="Main">
            <NavLink to="/school">My School</NavLink>
          </nav>
        )}
        {user && (
          <div className="user-info">
            <span>
              {user.full_name} ({user.role})
            </span>
            <NavLink to="/account">Account</NavLink>
            <button type="button" onClick={() => void logout()}>
              Log out
            </button>
          </div>
        )}
      </header>
      <div className="app-body" id="main-content" ref={mainRef} tabIndex={-1}>
        {children}
      </div>
    </div>
  )
}
