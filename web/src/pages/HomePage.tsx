import { Link } from 'react-router-dom'
import { Button } from '../components/Button'
import { useAuth } from '../auth/useAuth'
import './pages.css'

export function HomePage() {
  const { state, logout } = useAuth()
  if (state.status !== 'signed-in') return null
  const me = state.employee
  return (
    <div className="shell">
      <header className="topbar">
        <strong>사내 AI 비서</strong>
        <span className="topbar__me">
          {me.name} <span className="muted">{me.unitName}</span>
        </span>
        <Button onClick={logout}>로그아웃</Button>
      </header>
      <main className="page">
        <h1>{me.name}님, 안녕하세요</h1>
        <p className="muted">
          채팅과 승인함은 준비 중입니다. 부품은 <Link to="/design">디자인 부품</Link>에서 볼 수 있습니다.
        </p>
      </main>
    </div>
  )
}
