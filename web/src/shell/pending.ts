import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { api } from '../api/client'

/** 결재할 문서 수(결재 대기 + 대결 대기). 못 불러오면 null */
export async function fetchPendingCount(): Promise<number | null> {
  try {
    const [mine, delegated] = await Promise.all([
      api.GET('/inbox', { params: { query: { box: 'inbox' } } }),
      api.GET('/inbox', { params: { query: { box: 'delegated' } } }),
    ])
    if (!mine.data || !delegated.data) return null
    return mine.data.items.length + delegated.data.items.length
  } catch {
    return null
  }
}

/** 탐색 막대의 결재 건수. 화면을 옮길 때마다 다시 셉니다(결재하고 돌아오면 줄어듦) */
export function usePendingCount(): number | null {
  const { pathname } = useLocation()
  const [count, setCount] = useState<number | null>(null)
  useEffect(() => {
    let alive = true
    void fetchPendingCount().then((n) => alive && setCount(n))
    return () => {
      alive = false
    }
  }, [pathname])
  return count
}

/**
 * 로그인 뒤 첫 화면(역할별, ia.md 2절 안 A): 감사 조회 역할은 운영 지표, 결재할 문서가 있으면 결재, 그 밖에는 AI 비서
 */
export async function landingPath(roles: string[]): Promise<string> {
  if (roles.includes('auditor')) return '/ops/metrics'
  const n = await fetchPendingCount()
  return n && n > 0 ? '/approvals' : '/'
}
