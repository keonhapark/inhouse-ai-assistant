import { useEffect, useState } from 'react'
import { api, tokenStore } from '../api/client'
import type { Lookups } from './preview'

/**
 * 미리보기 카드가 쓰는 양식(필드 이름·순서)과 직원 이름 사전을 로그인한 사람마다 한 번만 불러옵니다(#556).
 * 직원 목록은 공개 필드(이름·부서·직급)만이고 erp 상한(100명)으로 한 번에 받습니다. 세 팩 모두 100명 아래입니다.
 * 둘 중 하나라도 실패하면 받은 것만 쓰고 캐시하지 않아, 다음에 카드를 그릴 때 다시 부릅니다.
 * 사전이 없으면 화면은 사전 이름과 ID로 보여 줍니다.
 */
type Entry = { token: string | null; value: Lookups; promise: Promise<Lookups> }
let cache: Entry | null = null

/** 시험에서 캐시를 비웁니다 */
export function resetLookups() {
  cache = null
}

function load(): Entry {
  const token = tokenStore.get()
  if (cache && cache.token === token) return cache
  const entry: Entry = { token, value: {}, promise: Promise.resolve({}) }
  entry.promise = Promise.all([
    api.GET('/approval-forms').then((r) => r.data?.items, () => undefined),
    api.GET('/employees', { params: { query: { limit: 100 } } }).then((r) => r.data?.items, () => undefined),
  ]).then(([forms, people]) => {
    entry.value = { forms, people: people ? new Map(people.map((p) => [p.id, p])) : undefined }
    if ((!forms || !people) && cache === entry) cache = null
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
