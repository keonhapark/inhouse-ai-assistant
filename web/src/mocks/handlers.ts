import { http, HttpResponse } from 'msw'
import type { Schemas } from '../api/client'
import { chatHandlers } from './chat'
import { inboxHandlers } from './inbox'
import { orgHandlers } from './org'
import { problem } from './problem'
import { agents, employeeForToken, employees, MOCK_PASSWORD, tokenFor } from './data'

// gateway 계약(contracts/openapi/gateway.yaml)의 모의 서버입니다. 경로는 계약의 servers(/api) 기준입니다.
const api = (path: string) => `*/api${path}`

const unauthorized = () => problem(401, 'unauthorized', '로그인이 필요합니다.')

export const handlers = [
  http.get(api('/health'), () => HttpResponse.json({ status: 'ok' as const })),

  http.post(api('/auth/login'), async ({ request }) => {
    const body = (await request.json()) as { employeeNo?: string; password?: string }
    const emp = employees.find((e) => e.employeeNo === body.employeeNo)
    if (!emp || body.password !== MOCK_PASSWORD) {
      return problem(401, 'unauthorized', '사번 또는 비밀번호가 맞지 않습니다.')
    }
    const res: Schemas['LoginResponse'] = {
      accessToken: tokenFor(emp),
      tokenType: 'Bearer',
      expiresIn: 3600,
      employee: emp,
    }
    return HttpResponse.json(res)
  }),

  http.get(api('/me'), ({ request }) => {
    const emp = employeeForToken(request.headers.get('Authorization'))
    return emp ? HttpResponse.json(emp) : unauthorized()
  }),

  http.get(api('/agents'), ({ request }) => {
    if (!employeeForToken(request.headers.get('Authorization'))) return unauthorized()
    return HttpResponse.json({ items: agents })
  }),

  ...chatHandlers,
  ...inboxHandlers,
  ...orgHandlers,
]
