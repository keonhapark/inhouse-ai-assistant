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

/** 운영 화면(감사 조회 역할만). 메뉴에 없을 뿐 아니라 주소로 들어와도 AI 비서로 보냅니다 */
function RequireAuditor({ children }: { children: ReactNode }) {
  const { state } = useAuth()
  if (state.status === 'signed-in' && !state.employee.roles.includes('auditor')) return <Navigate to="/" replace />
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
        <Route path="/approvals" element={<InboxPage />} />
        <Route path="/org" element={<OrgPage />} />
        <Route path="/agents" element={<AgentRegistryPage />} />
        <Route path="/ops/eval" element={<RequireAuditor><EvalReportPage /></RequireAuditor>} />
        <Route path="/ops/:tab" element={<RequireAuditor><AdminPage /></RequireAuditor>} />
        {/* 예전 주소(ux/research/ia.md 2절에서 바뀜) */}
        <Route path="/inbox" element={<Navigate to="/approvals" replace />} />
        <Route path="/admin" element={<Navigate to="/ops/metrics" replace />} />
        <Route path="/eval" element={<Navigate to="/ops/eval" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
