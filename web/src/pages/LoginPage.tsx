import { useEffect, useState, type FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { landingPath } from '../shell/pending'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { useAuth } from '../auth/useAuth'
import './pages.css'

export function LoginPage() {
  const { state, login } = useAuth()
  const location = useLocation()
  const [employeeNo, setEmployeeNo] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  if (state.status === 'signed-in') {
    // 가려던 화면이 AI 비서 첫 주소('/')뿐이면 역할별 첫 화면으로 보냅니다
    const from = (location.state as { from?: string } | null)?.from
    return from && from !== '/' ? <Navigate to={from} replace /> : <FirstScreen roles={state.employee.roles} />
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setPending(true)
    setError(null)
    const result = await login(employeeNo.trim(), password)
    setPending(false)
    if (!result.ok) setError(result.message)
  }

  return (
    <main className="login">
      <Card className="login__card" aria-labelledby="login-title">
        <form onSubmit={onSubmit} className="login__form" noValidate>
          <h1 id="login-title">사내 AI 비서</h1>
          <p className="muted">사번과 비밀번호로 로그인합니다.</p>
          <label>
            사번
            <input
              name="employeeNo"
              autoComplete="username"
              value={employeeNo}
              onChange={(e) => setEmployeeNo(e.target.value)}
              required
              autoFocus
            />
          </label>
          <label>
            비밀번호
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {error && (
            <p role="alert" className="alert">
              {error}
            </p>
          )}
          <Button type="submit" variant="primary" disabled={pending || !employeeNo || !password}>
            {pending ? '로그인 중' : '로그인'}
          </Button>
        </form>
      </Card>
    </main>
  )
}

/** 가려던 화면이 없으면 역할별 첫 화면으로 보냅니다(감사 조회 → 운영 지표, 결재할 문서 있음 → 결재, 그 밖 → AI 비서) */
function FirstScreen({ roles }: { roles: string[] }) {
  const [to, setTo] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    void landingPath(roles).then((p) => alive && setTo(p))
    return () => {
      alive = false
    }
  }, [roles])
  return to ? <Navigate to={to} replace /> : <p className="page muted">불러오는 중입니다.</p>
}
