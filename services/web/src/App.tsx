import { Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { AppLayout } from './layout/AppLayout'
import { LoginPage } from './pages/LoginPage'
import { SchedulePage } from './pages/SchedulePage'

function App() {
  return (
    <AuthProvider>
      <AppLayout>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/schedule"
            element={
              <ProtectedRoute allowedRoles={['dispatcher', 'transportation_admin']}>
                <SchedulePage />
              </ProtectedRoute>
            }
          />
          <Route path="/" element={<Navigate to="/schedule" replace />} />
          <Route path="*" element={<Navigate to="/schedule" replace />} />
        </Routes>
      </AppLayout>
    </AuthProvider>
  )
}

export default App
