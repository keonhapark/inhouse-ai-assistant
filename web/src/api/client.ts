import createClient, { type Middleware } from 'openapi-fetch'
import type { components, paths } from './schema'

export type Schemas = components['schemas']
export type Employee = Schemas['Employee']
export type Problem = Schemas['Problem']

const TOKEN_KEY = 'iaa.token'

// 직원 JWT는 탭을 닫으면 사라지도록 sessionStorage에 둡니다.
export const tokenStore = {
  get(): string | null {
    try {
      return sessionStorage.getItem(TOKEN_KEY)
    } catch {
      return null
    }
  },
  set(token: string | null) {
    try {
      if (token) sessionStorage.setItem(TOKEN_KEY, token)
      else sessionStorage.removeItem(TOKEN_KEY)
    } catch {
      // 저장소를 못 쓰면 이번 탭 동안만 메모리에 남깁니다(AuthProvider 상태).
    }
  },
}

let onUnauthorized: (() => void) | null = null

/** 401을 받으면 부를 함수를 정합니다(로그아웃). */
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn
}

const auth: Middleware = {
  onRequest({ request }) {
    const token = tokenStore.get()
    if (token && !request.headers.has('Authorization')) {
      request.headers.set('Authorization', `Bearer ${token}`)
    }
    return request
  },
  onResponse({ request, response }) {
    if (response.status === 401 && request.headers.has('Authorization')) {
      onUnauthorized?.()
    }
    return response
  },
}

export function apiBaseUrl(): string {
  return `${globalThis.location?.origin ?? 'http://localhost'}/api`
}

// fetch를 부를 때마다 globalThis.fetch를 찾습니다. 모의 서버(MSW)가 나중에 fetch를 바꿔도 따라갑니다.
export const api = createClient<paths>({ baseUrl: apiBaseUrl(), fetch: (req) => globalThis.fetch(req) })
api.use(auth)

/**
 * problem+json이면 title을 그대로(DESIGN.md), detail이 있으면 뒤에 붙여 돌려줍니다. 아니면 fallback.
 */
export function problemTitle(error: unknown, fallback = '요청을 처리하지 못했습니다.'): string {
  if (error && typeof error === 'object' && 'title' in error && typeof error.title === 'string' && error.title) {
    // 제목과 같은 말인 상세는 붙이지 않습니다(erp는 여러 오류에서 title과 detail이 같음, copy-audit.md 2절)
    const raw = 'detail' in error && typeof error.detail === 'string' ? error.detail.trim() : ''
    const same = (a: string, b: string) => a.replace(/[.\s]+$/, '') === b.replace(/[.\s]+$/, '')
    const detail = raw && !same(raw, error.title) && !error.title.includes(raw) ? ` ${raw}` : ''
    return error.title + detail
  }
  return fallback
}
