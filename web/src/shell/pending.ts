import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { api } from '../api/client'

/** 결재 화면이 결재를 처리하면 보내는 이벤트. 탐색 막대가 건수를 다시 셉니다 */
export const INBOX_CHANGED = 'inhouse-ai:inbox-changed'
export const notifyInboxChanged = () => window.dispatchEvent(new Event(INBOX_CHANGED))

/** 결재할 문서 수(결재 대기 + 대결 대기). 못 불러오거나 5초 안에 답이 없으면 null */
export async function fetchPendingCount(timeoutMs = 5000): Promise<number | null> {
  const ctl = new AbortController()
  const timer = setTimeout(() => ctl.abort(), timeoutMs)
  try {
    const [mine, delegated] = await Promise.all([
      api.GET('/inbox', { params: { query: { box: 'inbox' } }, signal: ctl.signal }),
      api.GET('/inbox', { params: { query: { box: 'delegated' } }, signal: ctl.signal }),
    ])
    if (!mine.data || !delegated.data) return null
    return mine.data.items.length + delegated.data.items.length
  } catch {
    return null
  } finally {
    clearTimeout(timer)
  }
}

/**
 * 탐색 막대의 결재 건수. 처음에 한 번, 결재 화면에 들어가거나 나올 때, 결재 화면이 처리했다고 알릴 때 다시 셉니다.
 * 다른 화면끼리 옮길 때는 다시 부르지 않습니다(목록 두 개를 받아 세므로).
 */
export function usePendingCount(): number | null {
  const { pathname } = useLocation()
  const inApprovals = pathname.startsWith('/approvals')
  const [count, setCount] = useState<number | null>(null)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    const refresh = () => void fetchPendingCount().then((n) => alive.current && setCount(n))
    refresh()
    window.addEventListener(INBOX_CHANGED, refresh)
    return () => {
      alive.current = false
      window.removeEventListener(INBOX_CHANGED, refresh)
    }
  }, [inApprovals])
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
