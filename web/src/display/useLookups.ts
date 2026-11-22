import { useEffect, useState } from 'react'
import { api, tokenStore } from '../api/client'
import type { Lookups } from './preview'

/**
 * 미리보기 카드가 쓰는 양식(필드 이름·순서)과 직원 이름 사전을 로그인한 사람마다 한 번만 불러옵니다(#556).
 * 직원 목록은 공개 필드(이름·부서·직급)만이고 erp 상한(100명) 안이라 한 번에 받습니다. 실패하면 빈 사전으로 두고
 * 화면은 사전 이름과 ID로 보여 줍니다.
 */
let cache: { token: string | null; value: Lookups; promise: Promise<Lookups> } | null = null

function load(): { value: Lookups; promise: Promise<Lookups> } {
  const token = tokenStore.get()
  if (cache && cache.token === token) return cache
  const entry: { token: string | null; value: Lookups; promise: Promise<Lookups> } = { token, value: {}, promise: Promise.resolve({}) }
  entry.promise = Promise.all([
    api.GET('/approval-forms').then((r) => r.data?.items, () => undefined),
    api.GET('/employees', { params: { query: { limit: 100 } } }).then((r) => r.data?.items, () => undefined),
  ]).then(([forms, people]) => {
    entry.value = { forms, people: people ? new Map(people.map((p) => [p.id, p])) : undefined }
    return entry.value
  })
  cache = entry
  return entry
}

export function useLookups(): Lookups {
  const [value, setValue] = useState<Lookups>(() => load().value)
  useEffect(() => {
    let alive = true
    void load().promise.then((v) => alive && setValue(v))
    return () => {
      alive = false
    }
  }, [])
  return value
}
