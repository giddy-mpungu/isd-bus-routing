import { useEffect, useRef, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import type { Role } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { LanguagePicker } from '../components/LanguagePicker'
import { useTranslation, type Phrase } from '../i18n'

// Each page's name for the browser tab and screen readers (WCAG 2.4.2).
// These pages are translated (src/i18n); the staff console's aren't.
const TRANSLATED_TITLES: Record<string, Phrase> = {
  '/login': 'Sign in',
  '/forgot-password': 'Forgot your password',
  '/reset-password': 'Choose a password',
  '/email-preferences': 'Bus time emails',
  '/account': 'Account',
  '/driver': 'My day',
  '/family': 'My family',
}
const STAFF_TITLES: Record<string, string> = {
  '/schedule': 'Schedule',
  '/field-trips': 'Field trips',
  '/templates': 'Recurring templates',
  '/reports': 'Reports',
  '/setup': 'Setup',
  '/users': 'Users',
  '/school': 'My school',
}

const STAFF_ROLES: ReadonlySet<Role> = new Set([
  'dispatcher',
  'transportation_admin',
  'school_admin',
])
const ROLE_NAMES: Partial<Record<Role, Phrase>> = {
  driver: 'driver',
  parent: 'parent',
  student: 'student',
}

export function AppLayout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const { pathname } = useLocation()
  const { t } = useTranslation()
  const mainRef = useRef<HTMLDivElement | null>(null)
  const firstRender = useRef(true)

  const translated = TRANSLATED_TITLES[pathname]
  const title = translated ? t(translated) : STAFF_TITLES[pathname]
  useEffect(() => {
    document.title = title ? `${title} · isd-bus-routing` : 'isd-bus-routing'
  }, [title])

  useEffect(() => {
    // After moving to another page, start screen readers and keyboards at
    // its content rather than wherever focus was (the link just pressed).
    if (firstRender.current) {
      firstRender.current = false
      return
    }
    mainRef.current?.focus()
  }, [pathname])

  function roleName(role: Role): string {
    const phrase = ROLE_NAMES[role]
    return phrase ? t(phrase) : role
  }

  return (
    <div className="app-shell">
      {/* WCAG 2.4.1: past the menu straight to the page. */}
      <a className="skip-link" href="#main-content">
        {t('Skip to main content')}
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
            <NavLink to="/driver">{t('My day')}</NavLink>
          </nav>
        )}
        {user && (user.role === 'student' || user.role === 'parent') && (
          <nav className="app-nav" aria-label="Main">
            <NavLink to="/family">{t('My Family')}</NavLink>
          </nav>
        )}
        {user && user.role === 'school_admin' && (
          <nav className="app-nav" aria-label="Main">
            <NavLink to="/school">My School</NavLink>
          </nav>
        )}
        {(!user || !STAFF_ROLES.has(user.role)) && <LanguagePicker />}
        {user && (
          <div className="user-info">
            <span>
              {user.full_name} ({roleName(user.role)})
            </span>
            <NavLink to="/account">{t('Account')}</NavLink>
            <button type="button" onClick={() => void logout()}>
              {t('Log out')}
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
