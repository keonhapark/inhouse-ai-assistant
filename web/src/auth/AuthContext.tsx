import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, problemTitle, setUnauthorizedHandler, tokenStore } from '../api/client'
import { AuthContext, type AuthState, type AuthValue } from './context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(() =>
    tokenStore.get() ? { status: 'loading' } : { status: 'anonymous' },
  )

  const logout = useCallback(() => {
    tokenStore.set(null)
    setState({ status: 'anonymous' })
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(logout)
    return () => setUnauthorizedHandler(null)
  }, [logout])

  // 저장된 토큰이 있으면 /me로 아직 유효한지 확인합니다.
  useEffect(() => {
    if (state.status !== 'loading') return
    let cancelled = false
    api.GET('/me').then(({ data }) => {
      if (cancelled) return
      if (data) setState({ status: 'signed-in', employee: data })
      else logout()
    }, () => {
      if (!cancelled) logout()
    })
    return () => {
      cancelled = true
    }
  }, [state.status, logout])

  const login = useCallback<AuthValue['login']>(async (employeeNo, password) => {
    try {
      const { data, error } = await api.POST('/auth/login', { body: { employeeNo, password } })
      if (!data) return { ok: false, message: problemTitle(error, '로그인하지 못했습니다.') }
      tokenStore.set(data.accessToken)
      setState({ status: 'signed-in', employee: data.employee })
      return { ok: true }
    } catch {
      return { ok: false, message: '서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.' }
    }
  }, [])

  const value = useMemo(() => ({ state, login, logout }), [state, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
