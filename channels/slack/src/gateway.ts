import type { components } from './schema.js'
import { readSse } from './sse.js'

export type Schemas = components['schemas']
export type ChatEvent = Schemas['ChatEvent']

/**
 * gateway 호출 실패. status는 HTTP 상태(연결 실패·끊김은 0)입니다.
 * message는 슬랙에 보여도 되는 문구입니다. 4xx는 problem+json의 title, 5xx와 연결 실패는 고정 문구이고,
 * detail 같은 원문은 슬랙에 올리지 않도록 internal에만 둡니다(로그용).
 */
export class GatewayError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly internal?: string,
    /** 429면 Retry-After(초) */
    readonly retryAfter?: number,
  ) {
    super(message)
  }
}

export const UNAVAILABLE = '사내 AI 비서가 응답하지 않습니다. 잠시 뒤 다시 시도해 주세요.'
export const RATE_LIMITED = '요청이 몰려 지금은 처리할 수 없습니다. 잠시 뒤 다시 시도해 주세요.'
export const MISCONFIGURED = '슬랙 연결 설정이 맞지 않아 처리하지 못했습니다. 관리자에게 알려 주세요.'

/** 브리지가 gateway에 바라는 것. 시험에서는 가짜로 바꿉니다. */
export interface Gateway {
  /** 슬랙 사용자 ID로 직원 토큰과 유효 시간(초)을 받습니다. 매핑이 없으면 null(gateway 403). */
  login(slackUserId: string): Promise<{ token: string; expiresIn: number } | null>
  createConversation(token: string): Promise<string>
  /** 메시지를 보내고 SSE 이벤트를 차례로 돌려줍니다. 마지막은 done입니다. */
  send(token: string, conversationId: string, content: string): AsyncGenerator<ChatEvent>
  decide(token: string, approvalId: string, decision: 'approve' | 'reject'): AsyncGenerator<ChatEvent>
  undo(token: string, actionId: string, idempotencyKey: string): Promise<Schemas['ActionResult']>
  notifications(token: string): Promise<Schemas['Notification'][]>
}

type Options = { baseUrl: string; bridgeSecret: string; fetch?: typeof fetch }

export function httpGateway({ baseUrl, bridgeSecret, fetch: f = fetch }: Options): Gateway {
  const url = (path: string) => `${baseUrl.replace(/\/$/, '')}${path}`

  async function call(token: string | null, path: string, init: RequestInit = {}): Promise<Response> {
    let res: Response
    try {
      res = await f(url(path), {
        ...init,
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...(init.headers as Record<string, string> | undefined),
        },
      })
    } catch (e) {
      throw new GatewayError(UNAVAILABLE, 0, e instanceof Error ? e.message : String(e))
    }
    if (!res.ok) throw await problem(res)
    return res
  }

  async function* stream(res: Response): AsyncGenerator<ChatEvent> {
    if (!res.body) throw new GatewayError('답을 받지 못했습니다. 잠시 뒤 다시 시도해 주세요.', res.status)
    let done = false
    for await (const msg of readSse(res.body)) {
      const e = JSON.parse(msg.data) as ChatEvent
      if (e.type === 'done') done = true
      yield e
    }
    // 계약상 마지막은 done입니다. 없이 닫히면 답이 잘린 것입니다.
    if (!done) throw new GatewayError('응답이 중간에 끊겼습니다. 잠시 뒤 다시 시도해 주세요.', 0)
  }

  return {
    async login(slackUserId) {
      try {
        const res = await call(null, '/auth/slack', {
          method: 'POST',
          headers: { 'X-Slack-Bridge-Secret': bridgeSecret },
          body: JSON.stringify({ slackUserId }),
        })
        const body = (await res.json()) as Schemas['LoginResponse']
        return { token: body.accessToken, expiresIn: body.expiresIn }
      } catch (e) {
        if (e instanceof GatewayError && e.status === 403) return null
        // 비밀값이 틀림(401)이나 gateway에 슬랙 로그인이 설정되지 않음(404)은 브리지 설정 문제입니다. 원문은 로그에만 둡니다.
        if (e instanceof GatewayError && (e.status === 401 || e.status === 404)) throw new GatewayError(MISCONFIGURED, e.status, e.internal)
        throw e
      }
    },
    async createConversation(token) {
      const res = await call(token, '/conversations', { method: 'POST', body: '{}' })
      return ((await res.json()) as Schemas['ConversationSummary']).conversationId
    },
    async *send(token, conversationId, content) {
      yield* stream(await call(token, `/conversations/${encodeURIComponent(conversationId)}/messages`, { method: 'POST', body: JSON.stringify({ content }) }))
    },
    async *decide(token, approvalId, decision) {
      yield* stream(await call(token, `/execution-approvals/${encodeURIComponent(approvalId)}`, { method: 'POST', body: JSON.stringify({ decision }) }))
    },
    async undo(token, actionId, idempotencyKey) {
      const res = await call(token, `/actions/${encodeURIComponent(actionId)}/undo`, { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey }, body: '{}' })
      return (await res.json()) as Schemas['ActionResult']
    },
    async notifications(token) {
      const res = await call(token, '/notifications')
      return ((await res.json()) as { items: Schemas['Notification'][] }).items
    },
  }
}

async function problem(res: Response): Promise<GatewayError> {
  let body: { title?: string; detail?: string } = {}
  try {
    body = (await res.json()) as typeof body
  } catch {
    // problem+json이 아니면 상태 코드만 씁니다.
  }
  const internal = [res.status, body.title, body.detail].filter(Boolean).join(' ')
  if (res.status >= 500) return new GatewayError(UNAVAILABLE, res.status, internal)
  if (res.status === 429) {
    const after = Number(res.headers.get('Retry-After'))
    return new GatewayError(RATE_LIMITED, 429, internal, Number.isFinite(after) && after > 0 ? after : undefined)
  }
  return new GatewayError(body.title || '요청을 처리할 수 없습니다. 계속되면 관리자에게 알려 주세요.', res.status, internal)
}
