import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import * as api from '../api/client'
import type { CurrentUser } from '../api/types'

interface AuthContextValue {
  user: CurrentUser | null
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // GET /users/me succeeds only if the browser holds a valid session
  // cookie — this alone is what makes "survives a page refresh" work.
  // No token is ever read, stored, or handled by this client.
  const refreshUser = useCallback(async () => {
    try {
      setUser(await api.getCurrentUser())
    } catch {
      setUser(null)
    }
  }, [])

  useEffect(() => {
    void refreshUser().finally(() => setIsLoading(false))
  }, [refreshUser])

  const login = useCallback(
    async (email: string, password: string) => {
      await api.login(email, password)
      await refreshUser()
    },
    [refreshUser],
  )

  const logout = useCallback(async () => {
    await api.logout()
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
