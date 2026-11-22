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

/** 명령 팔레트의 "새 대화"는 주소 상태(newChat)로 옵니다. 값이 바뀌면 채팅 화면을 새로 열어 빈 대화로 시작합니다 */
function ChatRoute() {
  const newChat = (useLocation().state as { newChat?: number } | null)?.newChat
  return <ChatPage key={newChat ?? 'chat'} />
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
        <Route path="/" element={<ChatRoute />} />
        <Route path="/approvals" element={<InboxPage />} />
        <Route path="/org" element={<OrgPage />} />
        <Route path="/agents" element={<AgentRegistryPage />} />
        <Route path="/ops/eval" element={<EvalReportPage />} />
        <Route path="/ops/:tab" element={<AdminPage />} />
        {/* 예전 주소(ux/research/ia.md 2절에서 바뀜) */}
        <Route path="/inbox" element={<Navigate to="/approvals" replace />} />
        <Route path="/admin" element={<Navigate to="/ops/metrics" replace />} />
        <Route path="/eval" element={<Navigate to="/ops/eval" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
