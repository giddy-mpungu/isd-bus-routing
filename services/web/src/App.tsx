import { Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { AppLayout } from './layout/AppLayout'
import { AccountPage } from './pages/AccountPage'
import { DriverPage } from './pages/DriverPage'
import { FamilyPage } from './pages/FamilyPage'
import { FieldTripsPage } from './pages/FieldTripsPage'
import { ForgotPasswordPage } from './pages/ForgotPasswordPage'
import { LoginPage } from './pages/LoginPage'
import { ReportsPage } from './pages/ReportsPage'
import { ResetPasswordPage } from './pages/ResetPasswordPage'
import { SchedulePage } from './pages/SchedulePage'
import { SchoolAdminPage } from './pages/SchoolAdminPage'
import { SetupPage } from './pages/SetupPage'
import { TemplatesPage } from './pages/TemplatesPage'
import { UsersPage } from './pages/UsersPage'

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
  if (user?.role === 'school_admin') {
    return <Navigate to="/school" replace />
  }
  return <Navigate to="/schedule" replace />
}

function App() {
  return (
    <AuthProvider>
      <AppLayout>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route
            path="/account"
            element={
              <ProtectedRoute
                allowedRoles={[
                  'driver',
                  'student',
                  'parent',
                  'school_admin',
                  'dispatcher',
                  'transportation_admin',
                ]}
              >
                <AccountPage />
              </ProtectedRoute>
            }
          />
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
            path="/users"
            element={
              // spec section 17: "user permissions" is transportation_admin
              // only, narrower than the rest of the dispatcher console.
              <ProtectedRoute
                allowedRoles={['transportation_admin']}
                deniedMessage="user management"
              >
                <UsersPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/templates"
            element={
              <ProtectedRoute
                allowedRoles={['dispatcher', 'transportation_admin']}
                deniedMessage="the dispatcher console"
              >
                <TemplatesPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/field-trips"
            element={
              <ProtectedRoute
                allowedRoles={['dispatcher', 'transportation_admin']}
                deniedMessage="the dispatcher console"
              >
                <FieldTripsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/reports"
            element={
              <ProtectedRoute
                allowedRoles={['dispatcher', 'transportation_admin']}
                deniedMessage="the dispatcher console"
              >
                <ReportsPage />
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
          <Route
            path="/school"
            element={
              <ProtectedRoute
                allowedRoles={['school_admin']}
                deniedMessage="the school administrator view"
              >
                <SchoolAdminPage />
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
