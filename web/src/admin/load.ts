import { useEffect, useState } from 'react'
import { problemTitle } from '../api/client'

export type Load<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ok'; data: T }

export const NETWORK = '서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.'

/**
 * key가 바뀔 때마다 fetcher를 부르고, 마지막 key의 결과만 남깁니다. 실패는 problem+json의 title(없으면 fallback)입니다.
 * 결과는 어느 key의 것인지 함께 두어, key가 바뀐 직후에는 앞 결과 대신 불러오는 중으로 봅니다.
 */
export function useLoad<T>(key: string, fetcher: () => Promise<{ data?: T; error?: unknown }>, fallback: string): Load<T> {
  const [state, setState] = useState<{ key: string; load: Load<T> } | null>(null)
  useEffect(() => {
    let current = true
    fetcher().then(
      ({ data, error }) =>
        current && setState({ key, load: data !== undefined ? { status: 'ok', data } : { status: 'error', message: problemTitle(error, fallback) } }),
      () => current && setState({ key, load: { status: 'error', message: NETWORK } }),
    )
    return () => {
      current = false
    }
    // fetcher는 key에 든 값으로만 달라집니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return state && state.key === key ? state.load : { status: 'loading' }
}

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 4 })
export const formatUsd = (n: number) => usd.format(n)
export const percent = (part: number, whole: number) => (whole > 0 ? Math.round((part / whole) * 100) : 0)

/** 비율 글자. 0보다 크면 0%로, 100보다 작으면 100%로 반올림하지 않습니다(외부 전송 여부를 잘못 읽지 않게). */
export function percentText(part: number, whole: number): string {
  if (whole <= 0) return '0%'
  const r = (part / whole) * 100
  if (r > 0 && r < 1) return '<1%'
  if (r > 99 && r < 100) return '>99%'
  return `${Math.round(r)}%`
}

type Page<T> = { items: T[]; nextCursor?: string | null }

/**
 * 커서로 넘기는 목록. key(조건)가 바뀌면 첫 쪽부터 다시 불러옵니다.
 * '더 보기'로 붙인 쪽은 그 첫 쪽 응답에 묶어 둡니다. 같은 조건으로 돌아와 첫 쪽을 새로 받으면 예전에 붙인 쪽은 버립니다.
 */
export function usePaged<T>(key: string, fetchPage: (cursor?: string) => Promise<{ data?: Page<T>; error?: unknown }>, fallback: string) {
  const first = useLoad<Page<T>>(key, () => fetchPage(), fallback)
  const base = first.status === 'ok' ? first.data : null
  const [more, setMore] = useState<{ base: Page<T>; items: T[]; nextCursor: string | null } | null>(null)
  const [moreError, setMoreError] = useState<{ base: Page<T>; message: string } | null>(null)
  const [loading, setLoading] = useState<Page<T> | null>(null)
  const extra = base && more?.base === base ? more : null

  const items = base ? [...base.items, ...(extra?.items ?? [])] : []
  const next = extra ? extra.nextCursor : (base?.nextCursor ?? null)

  async function loadMore() {
    if (!next || !base) return
    setLoading(base)
    setMoreError(null)
    try {
      const { data, error } = await fetchPage(next)
      if (data) setMore((cur) => ({ base, items: [...(cur?.base === base ? cur.items : []), ...data.items], nextCursor: data.nextCursor ?? null }))
      else setMoreError({ base, message: problemTitle(error, '다음 목록을 불러오지 못했습니다.') })
    } catch {
      setMoreError({ base, message: NETWORK })
    } finally {
      setLoading((cur) => (cur === base ? null : cur))
    }
  }

  return {
    first,
    items,
    next,
    loadMore,
    loadingMore: base !== null && loading === base,
    moreError: base && moreError?.base === base ? moreError.message : null,
  }
}
