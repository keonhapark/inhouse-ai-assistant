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
type PendingApproval = { conv: string; tool: string; summary: string; done: string; rejected: string; undoable: boolean }
const approvals = new Map<string, PendingApproval>()
const actions = new Map<string, { undone: boolean; summary: string; undoable: boolean }>()
let idSeq = 0

/** 시험에서는 0으로 두어 기다리지 않습니다. */
export const mockTiming = { eventDelayMs: import.meta.env.MODE === 'test' ? 0 : 120 }

const now = () => new Date().toISOString()
// 모델 이름은 gateway 별칭이 가리키는 모델입니다(gateway/litellm/config.yaml).
const LOCAL = { name: 'qwen3.5:9b', location: 'local' as const }
const EXTERNAL = { name: 'claude-haiku-5-5', location: 'external' as const }
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
  // 결재 회수는 되돌릴 수 없어(irreversible) 실행 전에 사람 확인을 받습니다(결정 0003).
  if (/회수/.test(content)) {
    const approvalId = `ap-${++idSeq}`
    approvals.set(approvalId, {
      conv: c.summary.conversationId,
      tool: 'approval_withdraw',
      summary: '휴가 결재 APR-0042를 회수했습니다.',
      done: '결재를 회수했습니다. 회수한 결재는 다시 상신해야 합니다.',
      rejected: '회수하지 않았습니다.',
      undoable: false,
    })
    const text = '결재 중인 휴가 결재 APR-0042(11. 24. 오후 반차)를 찾았습니다. 회수하면 실행 취소할 수 없습니다.'
    return [
      ...route(c, 'hr', 'keyword', '결재 회수 요청'),
      { type: 'tool_call', toolCall: { tool: 'approval_list_mine', risk: 'read', status: 'ok' } },
      ...words(text),
      { type: 'message', text, model: LOCAL },
      {
        type: 'approval_required',
        approval: {
          approvalId,
          tool: 'approval_withdraw',
          toolLabel: '결재 회수',
          risk: 'irreversible',
          expiresAt: new Date(Date.now() + 10 * 60_000).toISOString(),
          preview: {
            dryRun: true,
            operation: 'withdrawApproval',
            summary: '휴가 결재 APR-0042(11. 24. 오후 반차)를 회수합니다.',
            undoable: false,
            changes: [
              {
                op: 'update',
                resource: 'approval',
                resourceId: 'APR-0042',
                before: { status: 'in_progress' },
                after: { status: 'withdrawn' },
              },
            ],
          },
        },
      },
      { type: 'done', model: LOCAL },
    ]
  }
  // 회의실 예약은 되돌릴 수 있는 쓰기(reversible_write)라 바로 실행하고 되돌리기를 붙입니다(auto_with_undo).
  if (/회의실|예약/.test(content)) {
    const actionId = `act-${++idSeq}`
    const summary = '3층 소회의실을 내일 오후 2:00–3:00에 예약했습니다.'
    actions.set(actionId, { undone: false, summary, undoable: true })
    const text = '내일 오후 2:00–3:00에 3층 소회의실(6인)을 예약했습니다. 필요 없으면 실행 취소를 누르세요.'
    return [
      ...route(c, 'assistant', 'keyword', '회의실 예약 요청'),
      { type: 'tool_call', toolCall: { tool: 'room_list_availability', risk: 'read', status: 'ok' } },
      { type: 'tool_call', toolCall: { tool: 'room_reserve', risk: 'reversible_write', status: 'ok' } },
      { type: 'action', action: { actionId, tool: 'room_reserve', summary, undoable: true } },
      ...words(text),
      { type: 'message', text, model: EXTERNAL },
      { type: 'done', model: EXTERNAL },
    ]
  }
  // 답에 마크다운(굵게·목록·하위 목록·코드)이 든 경우(#529). 로컬 모델 답이 이런 형식으로 옵니다.
  if (/출장/.test(content)) {
    const text =
      '출장 숙박비 한도는 지역에 따라 다릅니다.\n\n*   **서울·광역시**: 1박 **10만 원**까지\n*   **그 밖의 지역**: 1박 **8만 원**까지\n    - 임원은 위 금액의 1.5배\n\n정산할 때는 `숙박 영수증`과 출장 품의 번호를 함께 붙입니다.'
    return [
      ...route(c, 'finance', 'llm', '출장비 규정 질의'),
      { type: 'tool_call', toolCall: { tool: 'policy_search', risk: 'read', status: 'ok' } },
      ...words(text),
      { type: 'message', text, model: LOCAL },
      {
        type: 'citations',
        citations: [{ docId: 'rules-travel', title: '출장비 규정', article: '제7조(숙박비)', quote: '숙박비는 별표 2의 지역별 한도 안에서 실비로 정산한다.', verified: true }],
      },
      { type: 'done', model: LOCAL },
    ]
  }
  if (/연차|휴가|규정/.test(content)) {
    const text = '입사 1년이 지나면 연차 15일이 생기고, 3년차부터 2년마다 1일씩 늘어납니다.'
    return [
      ...route(c, 'hr', 'llm', '연차 규정 질의'),
      { type: 'tool_call', toolCall: { tool: 'policy_search', risk: 'read', status: 'ok' } },
      ...words(text),
      { type: 'message', text, model: LOCAL },
      {
        type: 'citations',
        citations: [
          { docId: 'rules-work', title: '취업규칙', article: '제20조(연차휴가)', quote: '1년간 80퍼센트 이상 출근한 직원에게 15일의 유급휴가를 준다.', verified: true },
          { docId: 'rules-work', title: '취업규칙', article: '제20조 제4항', quote: '3년 이상 근속한 직원에게는 가산휴가를 준다.', verified: false },
        ],
      },
      { type: 'done', model: LOCAL },
    ]
  }
  const text = '말씀하신 내용을 맡을 부서를 찾지 못했습니다. 회의실 예약이나 연차 규정처럼 구체적으로 물어봐 주세요.'
  return [...route(c, 'assistant', 'fallback', '맞는 부서 없음'), ...words(text), { type: 'message', text }, { type: 'done' }]
}

/**
 * 사진을 붙인 메시지: 재무 에이전트가 영수증에서 읽은 값으로 경비 정산 미리보기를 냅니다(결정 0004 덧붙임: 사진을 읽은 턴은 승인을 받음).
 * 실제 읽기는 agent의 로컬 비전 모델이 하고, 모의 서버는 정해 둔 값을 돌려줍니다.
 */
function receipt(c: Conv): Draft[] {
  const approvalId = `ap-${++idSeq}`
  approvals.set(approvalId, {
    conv: c.summary.conversationId,
    tool: 'expense_request',
    summary: '경비 정산 결재 EXP-0107(42,000원)을 상신했습니다.',
    done: '경비 정산을 상신했습니다. 필요 없으면 실행 취소를 누르세요.',
    rejected: '상신하지 않았습니다.',
    undoable: true,
  })
  const text = '영수증에서 가맹점·날짜·금액을 읽었습니다. 아래 내용으로 경비 정산을 상신할까요?'
  return [
    ...route(c, 'finance', 'llm', '영수증 경비 정산'),
    ...words(text),
    { type: 'message', text, model: LOCAL },
    {
      type: 'approval_required',
      approval: {
        approvalId,
        tool: 'expense_request',
        toolLabel: '경비 정산 상신',
        risk: 'reversible_write',
        fromAttachments: true,
        expiresAt: new Date(Date.now() + 10 * 60_000).toISOString(),
        preview: {
          dryRun: true,
          operation: 'createExpenseRequest',
          summary: '경비 정산 결재를 올립니다(결재선: 팀장).',
          undoable: true,
          changes: [
            {
              op: 'create',
              resource: 'approval_document',
              resourceId: null,
              before: null,
              // 실제 gateway가 주는 모양(erp 결재 문서 dry-run)과 같게 둡니다
              after: {
                id: `doc_mock${idSeq}`,
                formId: 'expense',
                title: '경비 정산 - 한지우',
                requesterId: 'emp-1001',
                status: 'in_progress',
                fields: { amount: 42000, spent_on: '2026-11-20', merchant: '가온식당 성수점', purpose: '거래처 점심 식대', business_no: '214-86-12345' },
                amount: 42000,
                steps: [{ order: 1, approverId: 'emp-2001', status: 'pending', actedBy: null, onBehalfOf: null, delegationId: null, actedAt: null, comment: null }],
                currentStep: 1,
                version: 1,
                createdAt: new Date().toISOString(),
                updatedAt: new Date().toISOString(),
              },
            },
          ],
        },
      },
    },
    { type: 'done', model: LOCAL },
  ]
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
    const { content, attachments = [] } = (await request.json()) as { content: string; attachments?: { kind: string; dataUrl: string }[] }
    // gateway 계약: jpeg·png data URL, 3장까지, 한 장 5MB(디코딩 크기)
    if (attachments.length > 3) return problem(422, 'validation', '이미지는 3장까지 붙일 수 있습니다.')
    if (attachments.some((a) => !/^data:image\/(jpeg|png);base64,/.test(a.dataUrl))) {
      return problem(415, 'unsupported-media-type', 'JPEG·PNG 이미지만 받습니다.')
    }
    // base64 디코딩 크기: 4글자당 3바이트에서 끝의 패딩(=) 수를 뺍니다.
    const decoded = (u: string) => {
      const b64 = u.slice(u.indexOf(',') + 1)
      return (b64.length * 3) / 4 - (b64.endsWith('==') ? 2 : b64.endsWith('=') ? 1 : 0)
    }
    if (attachments.some((a) => decoded(a.dataUrl) > 5 * 1024 * 1024)) {
      return problem(413, 'payload-too-large', '이미지 한 장은 5MB까지입니다.')
    }
    // 기록에는 첨부 본문 없이 메타만 남깁니다(계약 AttachmentMeta). sha256은 모의 값입니다.
    conv.events.push({
      type: 'user_message',
      content,
      at: now(),
      ...(attachments.length
        ? {
            attachments: attachments.map((a) => ({
              kind: 'image' as const,
              mediaType: a.dataUrl.startsWith('data:image/png') ? ('image/png' as const) : ('image/jpeg' as const),
              bytes: Math.round(decoded(a.dataUrl)),
              sha256: '0'.repeat(64),
            })),
          }
        : {}),
    })
    conv.summary.title ??= content.slice(0, 30)
    conv.summary.updatedAt = now()
    const events = stamp(conv, attachments.length ? receipt(conv) : scenario(conv, content))
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
      actions.set(actionId, { undone: false, summary: ap.summary, undoable: ap.undoable })
      drafts.push(
        { type: 'action', action: { actionId, tool: ap.tool, summary: ap.summary, undoable: ap.undoable } },
        { type: 'message', text: ap.done },
      )
    } else {
      drafts.push({ type: 'message', text: ap.rejected })
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
    if (!act.undoable) return problem(409, 'invalid-state', '되돌릴 수 없는 행동입니다.')
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
