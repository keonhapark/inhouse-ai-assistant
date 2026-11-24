import { http, HttpResponse } from 'msw'
import type { Schemas } from '../api/client'
import { employeeForToken } from './data'
import { problem } from './problem'
import { registry } from './org'

type Egress = Schemas['EgressRecord']
type Audit = Schemas['audit.schema']

const api = (path: string) => `*/api${path}`
const HOUR = 3_600_000

/** auditor 역할이 아니면 403(계약: 관리자 콘솔 경로는 auditor만). */
function guard(request: Request): Response | null {
  const me = employeeForToken(request.headers.get('Authorization'))
  if (!me) return problem(401, 'unauthorized', '로그인이 필요합니다.')
  if (!me.roles.includes('auditor')) return problem(403, 'forbidden', '감사 조회 역할이 필요합니다.')
  return null
}

function range(url: URL): { since: number; until: number } | Response {
  const until = url.searchParams.get('until') ? Date.parse(url.searchParams.get('until')!) : Date.now()
  const since = url.searchParams.get('since') ? Date.parse(url.searchParams.get('since')!) : until - 24 * HOUR
  if (Number.isNaN(since) || Number.isNaN(until) || since > until) return problem(400, 'validation', '기간이 맞지 않습니다.')
  return { since, until }
}

/** 조각을 이어 붙이며 가린 자리의 위치(UTF-16)를 셉니다. 문자열은 가림 뒤 본문입니다. */
function redacted(messageIndex: number, parts: (string | [entity: string, placeholder: string])[]) {
  let content = ''
  const redactions: Egress['redactions'] = []
  for (const p of parts) {
    if (typeof p === 'string') content += p
    else {
      redactions.push({ entity: p[0], placeholder: p[1], messageIndex, start: content.length, end: content.length + p[1].length })
      content += p[1]
    }
  }
  return { content, redactions }
}

const SYSTEM = { role: 'system', content: '당신은 사내 업무를 돕는 비서입니다. 도구 결과만 근거로 답합니다.' }

function egressAt(minutesAgo: number, i: number, agentId: string, user: ReturnType<typeof redacted>, tokens: [number, number]): Egress {
  const agent = registry.find((a) => a.id === agentId)
  return {
    recordId: `egr-${i}`,
    at: new Date(Date.now() - minutesAgo * 60_000).toISOString(),
    agentId,
    agentName: agent?.name ?? null,
    conversationId: `conv-x${i}`,
    actorId: 'emp-1001',
    model: 'claude-haiku-5-5',
    usage: { promptTokens: tokens[0], completionTokens: tokens[1] },
    costUsd: Number(((tokens[0] * 0.1 + tokens[1] * 0.5) / 1_000_000).toFixed(6)),
    messages: [SYSTEM, { role: 'user', content: user.content }],
    redactions: user.redactions,
  }
}

const EGRESS: Egress[] = [
  egressAt(12, 1, 'assistant', redacted(1, ['내일 오후 2시에 4명 들어갈 회의실 잡아 줘. 확정되면 ', ['KR_PHONE', '[전화번호]'], '로 문자 부탁해.']), [412, 58]),
  egressAt(47, 2, 'procurement', redacted(1, ['베어링 200개 구매 요청 올려 줘. 거래처 담당자 메일은 ', ['EMAIL_ADDRESS', '[이메일]'], '이고 사업자번호는 ', ['KR_BRN', '[사업자등록번호]'], '야.']), [688, 121]),
  egressAt(95, 3, 'assistant', redacted(1, ['출장비 규정이 어떻게 돼?']), [305, 96]),
  egressAt(180, 4, 'assistant', redacted(1, ['방문객 출입 등록해 줘. 주민번호 ', ['KR_RRN', '[주민등록번호]'], ', 연락처 ', ['KR_PHONE', '[전화번호]'], '.']), [377, 40]),
  egressAt(60 * 30, 5, 'procurement', redacted(1, ['500만 원 넘는 구매는 누가 결재해?']), [290, 77]),
]

const KINDS: [Audit['kind'], Audit['source'], Audit['result'], string | null, Audit['riskLevel'], agentId: string][] = [
  ['route.decided', 'agent', 'ok', null, null, 'assistant'],
  ['tool.called', 'mcp', 'ok', 'room_list_availability', 'read', 'assistant'],
  ['erp.write', 'erp', 'ok', 'createRoomReservation', 'reversible_write', 'assistant'],
  ['llm.request', 'gateway', 'ok', null, null, 'procurement'],
  ['llm.redacted', 'gateway', 'ok', null, null, 'assistant'],
  ['tool.blocked', 'mcp', 'denied', 'delegation_register', 'reversible_write', 'hr'],
  ['execution_approval.requested', 'gateway', 'pending', 'approval_withdraw', 'irreversible', 'hr'],
  ['execution_approval.decided', 'gateway', 'ok', 'approval_withdraw', 'irreversible', 'finance'],
  ['erp.undo', 'erp', 'ok', 'undoAction', 'reversible_write', 'assistant'],
  ['rag.access_denied', 'rag', 'denied', null, null, 'finance'],
]
const ACTORS = ['emp-1001', 'emp-2001', 'emp-2002']

// 계약(/audit-events)은 시각 순(오래된 것부터)입니다. 실제 gateway와 같게 오래된 것부터 둡니다.
const AUDIT: Audit[] = Array.from({ length: 45 }, (_, i): Audit => {
  const [kind, source, result, operation, riskLevel, agentId] = KINDS[i % KINDS.length]
  return {
    eventId: `evt-${String(45 - i).padStart(3, '0')}`,
    occurredAt: new Date(Date.now() - (i * 37 + 3) * 60_000).toISOString(),
    source,
    kind,
    actor: { employeeId: ACTORS[i % ACTORS.length], viaDelegationToken: source !== 'erp' || kind === 'erp.write', agentId },
    conversationId: `conv-a${i % 7}`,
    operation,
    riskLevel,
    result,
    problemType: result === 'denied' ? 'urn:problem:policy-denied' : null,
    detail: kind === 'tool.blocked' ? '문서에서 온 지시로는 대결 등록을 부를 수 없습니다(신뢰 등급).' : kind === 'llm.redacted' ? '전화번호 1건을 가렸습니다.' : null,
    model: kind.startsWith('llm.') ? { name: 'claude-haiku-5-5', location: 'external', externalSent: true, redactions: kind === 'llm.redacted' ? 1 : 0 } : null,
  }
}).reverse()

/** 하루 기준 수를 기간 길이에 맞춰 늘립니다(모의 지표). */
function counts(base: [calls: number, blocked: Record<string, number>, local: number, external: number, cost: number], days: number): Schemas['OpsCounts'] {
  const [calls, blocked, local, external, cost] = base
  const k = Math.max(days, 1 / 24)
  const by = Object.fromEntries(Object.entries(blocked).map(([c, n]) => [c, Math.round(n * k)]))
  const ext = Math.round(external * k)
  return {
    calls: Math.round(calls * k),
    blocked: { total: Object.values(by).reduce((a, b) => a + b, 0), byCode: by },
    llmRequests: { local: Math.round(local * k), external: ext },
    externalCostUsd: Number((cost * k).toFixed(4)),
    unpricedRequests: ext > 0 ? Math.round(k) % 2 : 0,
  }
}

const DAILY: Record<string, Parameters<typeof counts>[0]> = {
  assistant: [64, { trust_violation: 2, tool_not_allowed: 1 }, 18, 71, 0.042],
  hr: [41, { policy_denied: 3, model_policy: 1 }, 96, 0, 0],
  finance: [17, { scope_missing: 1 }, 39, 0, 0],
  procurement: [12, { policy_denied: 1 }, 6, 25, 0.019],
}

function sum(items: Schemas['OpsCounts'][]): Schemas['OpsCounts'] {
  const byCode: Record<string, number> = {}
  for (const c of items) for (const [code, n] of Object.entries(c.blocked.byCode)) byCode[code] = (byCode[code] ?? 0) + n
  return {
    calls: items.reduce((a, c) => a + c.calls, 0),
    blocked: { total: items.reduce((a, c) => a + c.blocked.total, 0), byCode },
    llmRequests: { local: items.reduce((a, c) => a + c.llmRequests.local, 0), external: items.reduce((a, c) => a + c.llmRequests.external, 0) },
    externalCostUsd: Number(items.reduce((a, c) => a + c.externalCostUsd, 0).toFixed(4)),
    unpricedRequests: items.reduce((a, c) => a + (c.unpricedRequests ?? 0), 0),
  }
}

function page<T>(items: T[], url: URL, fallbackLimit: number) {
  const offset = Number(url.searchParams.get('cursor') ?? 0) || 0
  const limit = Number(url.searchParams.get('limit') ?? fallbackLimit)
  const slice = items.slice(offset, offset + limit)
  return { items: slice, nextCursor: offset + limit < items.length ? String(offset + limit) : null }
}

export const adminHandlers = [
  http.get(api('/ops/metrics'), ({ request }) => {
    const denied = guard(request)
    if (denied) return denied
    const r = range(new URL(request.url))
    if (r instanceof Response) return r
    const days = (r.until - r.since) / (24 * HOUR)
    const agents = registry.map((a) => ({ agentId: a.id, agentName: a.name, ...counts(DAILY[a.id] ?? [0, {}, 0, 0, 0], days) }))
    const totals = sum(agents)
    const now = new Date()
    const res: Schemas['OpsMetrics'] = {
      since: new Date(r.since).toISOString(),
      until: new Date(r.until).toISOString(),
      totals,
      agents,
      routing: {
        total: totals.calls,
        byMethod: {
          llm: Math.round(totals.calls * 0.58),
          keyword: Math.round(totals.calls * 0.27),
          explicit: Math.round(totals.calls * 0.1),
          fallback: totals.calls - Math.round(totals.calls * 0.58) - Math.round(totals.calls * 0.27) - Math.round(totals.calls * 0.1),
        },
      },
      budgets: {
        period: 'month',
        periodStart: new Date(now.getFullYear(), now.getMonth(), 1).toISOString(),
        agents: [
          { id: 'assistant', name: '전사 비서', limitUsd: 20, usedUsd: 0.88 },
          { id: 'procurement', name: '구매자재', limitUsd: 5, usedUsd: 5.02, exceeded: true },
        ],
        units: [
          { id: 'mgmt', name: '경영지원본부', limitUsd: 15, usedUsd: 0.61 },
          { id: 'production-div', name: '생산본부', limitUsd: 15, usedUsd: 5.02 },
          { id: 'it-ops', name: 'IT운영팀', limitUsd: 10, usedUsd: 0.27 },
        ],
      },
    }
    return HttpResponse.json(res)
  }),

  http.get(api('/ops/egress'), ({ request }) => {
    const denied = guard(request)
    if (denied) return denied
    const url = new URL(request.url)
    const r = range(url)
    if (r instanceof Response) return r
    const agentId = url.searchParams.get('agentId')
    const items = EGRESS.filter((e) => {
      const t = Date.parse(e.at)
      return t >= r.since && t <= r.until && (!agentId || e.agentId === agentId)
    })
    return HttpResponse.json(page(items, url, 50))
  }),

  http.get(api('/audit-events'), ({ request }) => {
    const denied = guard(request)
    if (denied) return denied
    const url = new URL(request.url)
    const r = range(url)
    if (r instanceof Response) return r
    const q = (k: string) => url.searchParams.get(k)
    const items = AUDIT.filter((e) => {
      const t = Date.parse(e.occurredAt)
      return (
        t >= r.since &&
        t <= r.until &&
        (!q('kind') || e.kind === q('kind')) &&
        (!q('agentId') || e.actor.agentId === q('agentId')) &&
        (!q('actorId') || e.actor.employeeId === q('actorId')) &&
        (!q('conversationId') || e.conversationId === q('conversationId'))
      )
    })
    return HttpResponse.json(page(items, url, 100))
  }),
]
