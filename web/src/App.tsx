import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from './auth/useAuth'
import { DesignPage } from './pages/DesignPage'
import { AppShell } from './pages/AppShell'
import { ChatPage } from './chat/ChatPage'
import { InboxPage } from './inbox/InboxPage'
import { LoginPage } from './pages/LoginPage'
import { AdminPage } from './admin/AdminPage'
import { EvalReportPage } from './eval/EvalReportPage'
import { AgentRegistryPage } from './org/AgentRegistryPage'
import { OrgPage } from './org/OrgPage'

function RequireAuth({ children }: { children: ReactNode }) {
  const { state } = useAuth()
  const location = useLocation()
  if (state.status === 'loading') return <p className="page muted">불러오는 중입니다.</p>
  if (state.status === 'anonymous') return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/design" element={<DesignPage />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route path="/" element={<ChatPage />} />
        <Route path="/inbox" element={<InboxPage />} />
        <Route path="/org" element={<OrgPage />} />
        <Route path="/agents" element={<AgentRegistryPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/eval" element={<EvalReportPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
