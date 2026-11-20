import { NavLink, Outlet } from 'react-router-dom'
import { Button } from '../components/Button'
import { useAuth } from '../auth/useAuth'
import './pages.css'

export function AppShell() {
  const { state, logout } = useAuth()
  if (state.status !== 'signed-in') return null
  const me = state.employee
  return (
    <div className="shell">
      <header className="topbar">
        <strong>사내 AI 비서</strong>
        <nav className="topbar__nav" aria-label="화면">
          <NavLink to="/" end>
            채팅
          </NavLink>
          <NavLink to="/inbox">승인함</NavLink>
          <NavLink to="/org">조직도</NavLink>
          <NavLink to="/agents">에이전트</NavLink>
          {me.roles.includes('auditor') && <NavLink to="/admin">관리</NavLink>}
        </nav>
        <span className="topbar__me">
          {me.name} <span className="muted">{me.unitName}</span>
        </span>
        <Button onClick={logout}>로그아웃</Button>
      </header>
      <Outlet />
    </div>
  )
}
