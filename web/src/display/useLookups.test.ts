import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { tokenStore } from '../api/client'
import { server } from '../mocks/node'
import { useLookups } from './useLookups'

describe('useLookups', () => {
  it('양식과 직원 사전을 불러오고 같은 토큰이면 다시 부르지 않습니다', async () => {
    tokenStore.set('mock.emp-2001')
    let calls = 0
    server.events.on('request:start', ({ request }) => {
      if (request.url.includes('/approval-forms')) calls++
    })
    const a = renderHook(() => useLookups())
    await waitFor(() => expect(a.result.current.people?.get('emp-2001')?.name).toBe('서도윤'))
    expect(a.result.current.forms?.find((f) => f.id === 'expense')?.name).toBe('경비 정산')
    const b = renderHook(() => useLookups())
    await waitFor(() => expect(b.result.current.forms).toBeDefined())
    expect(calls).toBe(1)
    server.events.removeAllListeners()
  })

  it('실패하면 캐시하지 않고 다음에 다시 부릅니다', async () => {
    tokenStore.set('mock.emp-2001')
    server.use(http.get('*/api/approval-forms', () => HttpResponse.json({}, { status: 503 }), { once: true }))
    const a = renderHook(() => useLookups())
    await waitFor(() => expect(a.result.current.people).toBeDefined())
    expect(a.result.current.forms).toBeUndefined()
    const b = renderHook(() => useLookups())
    await waitFor(() => expect(b.result.current.forms?.length).toBeGreaterThan(0))
  })

  it('다른 사람으로 로그인하면 다시 부릅니다', async () => {
    tokenStore.set('mock.emp-2001')
    const a = renderHook(() => useLookups())
    await waitFor(() => expect(a.result.current.forms).toBeDefined())
    tokenStore.set('mock.emp-1001')
    let again = false
    server.events.on('request:start', ({ request }) => {
      if (request.url.includes('/approval-forms') && request.headers.get('Authorization') === 'Bearer mock.emp-1001') again = true
    })
    renderHook(() => useLookups())
    await waitFor(() => expect(again).toBe(true))
    server.events.removeAllListeners()
  })
})
