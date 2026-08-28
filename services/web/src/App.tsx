import { Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { AppLayout } from './layout/AppLayout'
import { DriverPage } from './pages/DriverPage'
import { FamilyPage } from './pages/FamilyPage'
import { LoginPage } from './pages/LoginPage'
import { SchedulePage } from './pages/SchedulePage'
import { SetupPage } from './pages/SetupPage'

function RoleHome() {
  // No role has a reason to land on the dispatcher console by default
  // (and ProtectedRoute would just block them there) — route each
  // role to the page it's actually built for.
  const { user, isLoading } = useAuth()
  if (isLoading) {
    return <p>Loading…</p>
  }
  if (user?.role === 'driver') {
    return <Navigate to="/driver" replace />
  }
  if (user?.role === 'student' || user?.role === 'parent') {
    return <Navigate to="/family" replace />
  }
  return <Navigate to="/schedule" replace />
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
          <Route
            path="/family"
            element={
              <ProtectedRoute allowedRoles={['student', 'parent']} deniedMessage="the family app">
                <FamilyPage />
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
