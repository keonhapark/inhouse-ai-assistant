import { useEffect, useState, type FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { landingPath } from '../shell/pending'
import { Sparkles } from 'lucide-react'
import { Button } from '../components/Button'
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

  const errorId = error ? 'login-error' : undefined
  return (
    <main className="login" aria-labelledby="login-title">
      <form onSubmit={onSubmit} className="login__sheet" noValidate>
        <span className="login__logo" aria-hidden>
          <Sparkles />
        </span>
        <h1 id="login-title" className="login__title">
          사내 AI 비서
        </h1>
        <p className="login__intro">결재, 경비 정산, 회의실 예약, 사내 규정 질문을 대화로 처리합니다.</p>
        <label className="login__field">
          <span>사번</span>
          <input
            name="employeeNo"
            autoComplete="username"
            value={employeeNo}
            onChange={(e) => setEmployeeNo(e.target.value)}
            aria-invalid={!!error}
            aria-describedby={errorId}
            required
            autoFocus
          />
        </label>
        <label className="login__field">
          <span>비밀번호</span>
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={!!error}
            aria-describedby={errorId}
            required
          />
        </label>
        {error && (
          <p role="alert" id="login-error" className="alert">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" className="login__submit" disabled={pending || !employeeNo || !password}>
          {pending ? '로그인 중' : '로그인'}
        </Button>
        <p className="login__help">사번이나 비밀번호를 모르면 IT 담당 부서에 문의해 주세요.</p>
      </form>
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
  return to ? <Navigate to={to} replace /> : <p role="status" className="page-loading">불러오는 중입니다.</p>
}
