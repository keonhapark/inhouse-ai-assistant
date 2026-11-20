import { http, HttpResponse } from 'msw'
import type { Employee, Schemas } from '../api/client'
import { agents, employeeForToken } from './data'
import { problem } from './problem'

type ChatEvent = Schemas['ChatEvent']
type Summary = Schemas['ConversationSummary']
type HistoryEvent = Schemas['Conversation']['events'][number]
type Draft = Omit<ChatEvent, 'conversationId' | 'seq' | 'at'>

// 모의 대화 저장소입니다. 메시지 내용의 낱말로 시나리오를 고릅니다(실제 라우팅과는 관계없음).
type Conv = { summary: Summary; owner: string; events: HistoryEvent[]; seq: number }
const convs = new Map<string, Conv>()
const approvals = new Map<string, { conv: string; title: string }>()
const actions = new Map<string, { undone: boolean; summary: string }>()
let idSeq = 0

/** 시험에서는 0으로 두어 기다리지 않습니다. */
export const mockTiming = { eventDelayMs: import.meta.env.MODE === 'test' ? 0 : 120 }

const now = () => new Date().toISOString()
const agentName = (id: string) => agents.find((a) => a.id === id)?.name ?? id

function stamp(c: Conv, drafts: Draft[]): ChatEvent[] {
  return drafts.map((d) => {
    const e: ChatEvent = { ...d, conversationId: c.summary.conversationId, seq: c.seq++, at: now() }
    c.events.push(e)
    if (e.type === 'route' && e.route) {
      c.summary.agentId = e.route.agentId ?? null
      c.summary.agentName = e.route.agentName ?? null
    }
    return e
  })
}

function sseResponse(events: ChatEvent[]): Response {
  const enc = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    async start(ctrl) {
      for (const e of events) {
        if (mockTiming.eventDelayMs) await new Promise((r) => setTimeout(r, mockTiming.eventDelayMs))
        ctrl.enqueue(enc.encode(`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`))
      }
      ctrl.close()
    },
  })
  return new Response(body, { headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' } })
}

function route(c: Conv, agentId: string, method: 'llm' | 'keyword' | 'fallback', reason: string): Draft[] {
  if (c.summary.agentId) return []
  return [{ type: 'route', route: { agentId, agentName: agentName(agentId), method: c.summary.agentId ? 'explicit' : method, reason } }]
}

function words(text: string): Draft[] {
  return text.split(/(?<= )/).map((t) => ({ type: 'delta' as const, text: t }))
}

function scenario(c: Conv, content: string): Draft[] {
  if (/급여|연봉/.test(content)) {
    return [
      ...route(c, 'hr', 'keyword', '급여 문의'),
      { type: 'blocked', blocked: { code: 'tool_not_allowed', reason: '이 에이전트는 다른 직원의 급여 정보를 볼 수 없습니다.' } },
      { type: 'done' },
    ]
  }
  if (/회의실|예약/.test(content)) {
    const approvalId = `ap-${++idSeq}`
    approvals.set(approvalId, { conv: c.summary.conversationId, title: '3층 소회의실 예약' })
    const text = '내일 14:00–15:00에 3층 소회의실(6인)이 비어 있습니다. 아래 내용으로 예약할까요?'
    return [
      ...route(c, 'assistant', 'keyword', '회의실 예약 요청'),
      { type: 'tool_call', toolCall: { tool: 'room_list_availability', risk: 'read', status: 'ok' } },
      ...words(text),
      { type: 'message', text, model: { name: 'gpt-4.1-mini', location: 'external' } },
      {
        type: 'approval_required',
        approval: {
          approvalId,
          tool: 'room_reserve',
          toolLabel: '회의실 예약',
          risk: 'reversible_write',
          expiresAt: new Date(Date.now() + 10 * 60_000).toISOString(),
          preview: {
            dryRun: true,
            operation: 'reserveRoom',
            summary: '3층 소회의실을 내일 14:00–15:00에 예약합니다.',
            undoable: true,
            changes: [
              {
                op: 'create',
                resource: 'room_reservation',
                resourceId: null,
                before: null,
                after: { room: '3층 소회의실', start: '14:00', end: '15:00', attendees: 4 },
              },
            ],
          },
        },
      },
      { type: 'done' },
    ]
  }
  if (/연차|휴가|규정/.test(content)) {
    const text = '입사 1년이 지나면 연차 15일이 생기고, 3년차부터 2년마다 1일씩 늘어납니다.'
    return [
      ...route(c, 'hr', 'llm', '연차 규정 질의'),
      { type: 'tool_call', toolCall: { tool: 'policy_search', risk: 'read', status: 'ok' } },
      ...words(text),
      { type: 'message', text, model: { name: 'qwen3.5:9b', location: 'local' } },
      {
        type: 'citations',
        citations: [
          { docId: 'rules-work', title: '취업규칙', article: '제20조(연차휴가)', quote: '1년간 80퍼센트 이상 출근한 직원에게 15일의 유급휴가를 준다.', verified: true },
          { docId: 'rules-work', title: '취업규칙', article: '제20조 제4항', quote: '3년 이상 근속한 직원에게는 가산휴가를 준다.', verified: false },
        ],
      },
      { type: 'done', model: { name: 'qwen3.5:9b', location: 'local' } },
    ]
  }
  const text = '말씀하신 내용을 맡을 부서를 찾지 못했습니다. 회의실 예약이나 연차 규정처럼 구체적으로 물어봐 주세요.'
  return [...route(c, 'assistant', 'fallback', '맞는 부서 없음'), ...words(text), { type: 'message', text }, { type: 'done' }]
}

function owned(request: Request, id: string): { me?: Employee; conv?: Conv } {
  const me = employeeForToken(request.headers.get('Authorization'))
  const conv = convs.get(id)
  return { me, conv: conv && me && conv.owner === me.id ? conv : undefined }
}

const api = (path: string) => `*/api${path}`
const unauthorized = () => problem(401, 'unauthorized', '로그인이 필요합니다.')
const notFound = () => problem(404, 'not-found', '대화를 찾지 못했습니다.')

export function resetMockChat() {
  convs.clear()
  approvals.clear()
  actions.clear()
}

export const chatHandlers = [
  http.get(api('/conversations'), ({ request }) => {
    const me = employeeForToken(request.headers.get('Authorization'))
    if (!me) return unauthorized()
    const items = [...convs.values()]
      .filter((c) => c.owner === me.id)
      .map((c) => c.summary)
      .sort((a, b) => (b.updatedAt ?? b.createdAt).localeCompare(a.updatedAt ?? a.createdAt))
    return HttpResponse.json({ items })
  }),

  http.post(api('/conversations'), async ({ request }) => {
    const me = employeeForToken(request.headers.get('Authorization'))
    if (!me) return unauthorized()
    const body = (await request.json().catch(() => ({}))) as { agentId?: string }
    if (body.agentId && !agents.some((a) => a.id === body.agentId && a.callable)) {
      return problem(403, 'forbidden', '이 에이전트를 부를 수 없습니다.')
    }
    const id = `conv-${++idSeq}`
    const summary: Summary = {
      conversationId: id,
      agentId: body.agentId ?? null,
      agentName: body.agentId ? agentName(body.agentId) : null,
      title: null,
      status: 'active',
      createdAt: now(),
      updatedAt: now(),
    }
    convs.set(id, { summary, owner: me.id, events: [], seq: 0 })
    return HttpResponse.json(summary, { status: 201 })
  }),

  http.get(api('/conversations/:id'), ({ request, params }) => {
    const { me, conv } = owned(request, String(params.id))
    if (!me) return unauthorized()
    if (!conv) return notFound()
    return HttpResponse.json({ ...conv.summary, events: conv.events })
  }),

  http.post(api('/conversations/:id/messages'), async ({ request, params }) => {
    const { me, conv } = owned(request, String(params.id))
    if (!me) return unauthorized()
    if (!conv) return notFound()
    if (conv.summary.status === 'awaiting_approval') {
      return problem(409, 'invalid-state', '실행 승인을 기다리는 중입니다. 미리보기 카드에서 먼저 실행하거나 취소해 주세요.')
    }
    const { content } = (await request.json()) as { content: string }
    conv.events.push({ type: 'user_message', content, at: now() })
    conv.summary.title ??= content.slice(0, 30)
    conv.summary.updatedAt = now()
    const events = stamp(conv, scenario(conv, content))
    if (events.some((e) => e.type === 'approval_required')) conv.summary.status = 'awaiting_approval'
    return sseResponse(events)
  }),

  http.post(api('/execution-approvals/:id'), async ({ request, params }) => {
    const me = employeeForToken(request.headers.get('Authorization'))
    if (!me) return unauthorized()
    const approvalId = String(params.id)
    const ap = approvals.get(approvalId)
    const conv = ap && convs.get(ap.conv)
    if (!ap || !conv || conv.owner !== me.id) return problem(404, 'not-found', '실행 승인을 찾지 못했습니다.')
    if (conv.summary.status !== 'awaiting_approval') return problem(409, 'invalid-state', '이미 결정한 실행 승인입니다.')
    const { decision } = (await request.json()) as { decision: 'approve' | 'reject' }
    conv.summary.status = 'active'
    conv.summary.updatedAt = now()
    const drafts: Draft[] = [{ type: 'approval_decided', decision: { approvalId, decision } }]
    if (decision === 'approve') {
      const actionId = `act-${++idSeq}`
      const summary = `${ap.title}을 했습니다.`
      actions.set(actionId, { undone: false, summary })
      drafts.push(
        { type: 'action', action: { actionId, tool: 'room_reserve', summary, undoable: true } },
        { type: 'message', text: '예약했습니다. 필요 없으면 되돌리기를 누르면 됩니다.' },
      )
    } else {
      drafts.push({ type: 'message', text: '예약하지 않았습니다.' })
    }
    drafts.push({ type: 'done' })
    return sseResponse(stamp(conv, drafts))
  }),

  http.post(api('/actions/:id/undo'), ({ request, params }) => {
    if (!employeeForToken(request.headers.get('Authorization'))) return unauthorized()
    const key = request.headers.get('Idempotency-Key')
    if (!key || key.length < 8) return problem(400, 'idempotency-key-required', 'Idempotency-Key가 필요합니다.')
    const actionId = String(params.id)
    const act = actions.get(actionId)
    if (!act) return problem(404, 'not-found', '행동을 찾지 못했습니다.')
    if (act.undone) return problem(409, 'invalid-state', '이미 되돌린 행동입니다.')
    act.undone = true
    const res: Schemas['ActionResult'] = {
      actionId: `act-${++idSeq}`,
      operation: 'undoAction',
      summary: `되돌림: ${act.summary}`,
      changes: [],
      undoable: false,
      resource: {},
      undoOf: actionId,
    }
    return HttpResponse.json(res, { status: 201 })
  }),
]
