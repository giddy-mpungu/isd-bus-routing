import { Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { AppLayout } from './layout/AppLayout'
import { DriverPage } from './pages/DriverPage'
import { LoginPage } from './pages/LoginPage'
import { SchedulePage } from './pages/SchedulePage'
import { SetupPage } from './pages/SetupPage'

function RoleHome() {
  // A driver has no reason to land on the dispatcher console (and
  // ProtectedRoute would just block them there) — route each role to
  // the page it's actually built for.
  const { user, isLoading } = useAuth()
  if (isLoading) {
    return <p>Loading…</p>
  }
  return <Navigate to={user?.role === 'driver' ? '/driver' : '/schedule'} replace />
}

function App() {
  return (
    <AuthProvider>
      <AppLayout>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/schedule"
            element={
              <ProtectedRoute
                allowedRoles={['dispatcher', 'transportation_admin']}
                deniedMessage="the dispatcher console"
              >
                <SchedulePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/setup"
            element={
              <ProtectedRoute
                allowedRoles={['dispatcher', 'transportation_admin']}
                deniedMessage="the dispatcher console"
              >
                <SetupPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/driver"
            element={
              <ProtectedRoute allowedRoles={['driver']} deniedMessage="the driver app">
                <DriverPage />
              </ProtectedRoute>
            }
          />
          <Route path="/" element={<RoleHome />} />
          <Route path="*" element={<RoleHome />} />
        </Routes>
      </AppLayout>
    </AuthProvider>
  )
}

export default App
