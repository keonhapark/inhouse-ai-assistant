import { http, HttpResponse } from 'msw'
import type { Employee, Schemas } from '../api/client'
import { directory, employeeForToken } from './data'
import { problem } from './problem'

type Doc = Schemas['ApprovalDocument']
type Delegation = Schemas['Delegation']
type InboxItem = Schemas['InboxItem']

// 실제 erp는 팩 forms.yaml의 fields를 그대로 돌려줍니다. 화면은 title·x-labels가 있으면 씁니다.
const LEAVE_SCHEMA = {
  type: 'object',
  properties: {
    leave_type: { type: 'string', title: '종류', 'x-labels': { annual: '연차', half_pm: '오후 반차' } },
    start_date: { type: 'string', format: 'date', title: '시작일' },
    end_date: { type: 'string', format: 'date', title: '종료일' },
    reason: { type: 'string', title: '사유' },
  },
}

// 제조 팩 forms.yaml의 경비 정산 필드(채팅 미리보기 카드와 승인함이 필드 이름·순서를 여기서 읽습니다)
export const EXPENSE_SCHEMA = {
  type: 'object',
  properties: {
    amount: { type: 'integer', title: '금액' },
    spent_on: { type: 'string', format: 'date', title: '사용일' },
    merchant: { type: 'string', title: '가맹점' },
    business_no: { type: 'string', title: '사업자번호' },
    purpose: { type: 'string', title: '목적' },
  },
}

const FORMS: Record<string, string> = { leave: '휴가 신청', expense: '경비 정산', purchase: '구매 요청' }
const DAY = 86_400_000

let docs: Doc[] = []
let delegations: Delegation[] = []
let idSeq = 0

function iso(offsetMs: number) {
  return new Date(Date.now() + offsetMs).toISOString()
}

/** 모의 결재 문서와 위임을 처음 상태로 되돌립니다. */
export function resetMockInbox() {
  idSeq = 0
  const step = (order: number, approverId: string, status: Schemas['ApprovalStep']['status'], extra: object = {}) => ({
    order,
    approverId,
    status,
    actedBy: null,
    onBehalfOf: null,
    delegationId: null,
    actedAt: null,
    comment: null,
    ...extra,
  })
  docs = [
    {
      id: 'doc-101',
      formId: 'leave',
      title: '연차 휴가 신청(11/27~11/28)',
      requesterId: 'emp-1001',
      status: 'in_progress',
      fields: { leave_type: 'annual', start_date: '2026-11-27', end_date: '2026-11-28', reason: '개인 사정' },
      amount: null,
      steps: [step(1, 'emp-2001', 'pending')],
      currentStep: 1,
      version: 1,
      createdAt: iso(-2 * 3600_000),
    },
    {
      id: 'doc-102',
      formId: 'expense',
      title: '11월 출장 경비 정산',
      requesterId: 'emp-1002',
      status: 'in_progress',
      fields: { 출장지: '창원 공장', 기간: '11/12~11/13' },
      amount: 320000,
      steps: [step(1, 'emp-2002', 'pending'), step(2, 'emp-3001', 'waiting')],
      currentStep: 1,
      version: 3,
      createdAt: iso(-DAY),
    },
    {
      id: 'doc-103',
      formId: 'leave',
      title: '반차 신청(11/18 오후)',
      requesterId: 'emp-1002',
      status: 'approved',
      fields: { leave_type: 'half_pm', start_date: '2026-11-18', end_date: '2026-11-18', reason: '병원' },
      amount: null,
      steps: [step(1, 'emp-2001', 'approved', { actedBy: 'emp-2001', actedAt: iso(-3 * DAY) })],
      currentStep: null,
      version: 2,
      createdAt: iso(-4 * DAY),
    },
    {
      id: 'doc-104',
      formId: 'purchase',
      title: '교육용 노트북 2대 구매',
      requesterId: 'emp-2001',
      status: 'in_progress',
      fields: { 품목: '노트북', 수량: 2 },
      amount: 2800000,
      steps: [step(1, 'emp-3001', 'pending')],
      currentStep: 1,
      version: 1,
      createdAt: iso(-5 * 3600_000),
    },
  ]
  delegations = [
    {
      id: 'dlg-1',
      delegatorId: 'emp-2002',
      delegateId: 'emp-2001',
      startsAt: iso(-DAY),
      endsAt: iso(2 * DAY),
      scope: { formTypes: ['*'], maxAmount: 1000000 },
      reason: '출장',
      status: 'active',
      registeredBy: 'emp-2002',
      revokedAt: null,
      revokedBy: null,
      createdAt: iso(-DAY),
    },
  ]
}
resetMockInbox()

const nameOf = (id: string) => directory[id]?.name ?? id

function delegationStatus(d: Delegation): Delegation['status'] {
  if (d.revokedAt) return 'revoked'
  const now = Date.now()
  if (now < Date.parse(d.startsAt)) return 'scheduled'
  if (now >= Date.parse(d.endsAt)) return 'expired'
  return 'active'
}

function inScope(d: Delegation, doc: Doc) {
  const forms = d.scope.formTypes
  const max = d.scope.maxAmount
  return (forms.includes('*') || forms.includes(doc.formId)) && (max == null || doc.amount == null || doc.amount <= max)
}

function current(doc: Doc) {
  return doc.status === 'in_progress' ? doc.steps.find((s) => s.order === doc.currentStep) : undefined
}

/** 내가 이 문서를 지금 결재할 수 있게 하는 위임 */
function delegationFor(me: Employee, doc: Doc) {
  const step = current(doc)
  if (!step || step.approverId === me.id) return undefined
  return delegations.find(
    (d) => d.delegatorId === step.approverId && d.delegateId === me.id && delegationStatus(d) === 'active' && inScope(d, doc),
  )
}

function view(me: Employee, doc: Doc): InboxItem {
  // steps는 계약상 erp 단계와 이름의 allOf입니다. 생성 타입이 교집합 배열이라 한 번 바꿔 둡니다.
  const d = delegationFor(me, doc)
  const copy = structuredClone(doc)
  return {
    ...copy,
    steps: copy.steps.map((s) => ({ ...s, approverName: nameOf(s.approverId), actedByName: s.actedBy ? nameOf(s.actedBy) : null })),
    formName: FORMS[doc.formId] ?? doc.formId,
    requesterName: nameOf(doc.requesterId),
    requesterUnitName: directory[doc.requesterId]?.unitName,
    viaDelegation: d
      ? { delegationId: d.id, originalApproverId: d.delegatorId, originalApproverName: nameOf(d.delegatorId), endsAt: d.endsAt }
      : null,
  } as unknown as InboxItem
}

function inBox(me: Employee, doc: Doc, box: string) {
  switch (box) {
    case 'inbox':
      return current(doc)?.approverId === me.id
    case 'delegated':
      return !!delegationFor(me, doc)
    case 'done':
      return doc.steps.some((s) => s.actedBy === me.id)
    case 'outbox':
      return doc.requesterId === me.id
    default:
      return false
  }
}

function delegationView(d: Delegation): Schemas['DelegationView'] {
  return { ...structuredClone(d), status: delegationStatus(d), delegatorName: nameOf(d.delegatorId), delegateName: nameOf(d.delegateId) }
}

const api = (path: string) => `*/api${path}`
const unauthorized = () => problem(401, 'unauthorized', '로그인이 필요합니다.')
const keyRequired = () => problem(400, 'idempotency-key-required', 'Idempotency-Key가 필요합니다.')
const hasKey = (r: Request) => (r.headers.get('Idempotency-Key')?.length ?? 0) >= 8

function decide(kind: 'approve' | 'reject') {
  return http.post(api(`/inbox/:id/${kind}`), async ({ request, params }) => {
    const me = employeeForToken(request.headers.get('Authorization'))
    if (!me) return unauthorized()
    if (!hasKey(request)) return keyRequired()
    const doc = docs.find((d) => d.id === params.id)
    if (!doc) return problem(404, 'not-found', '결재 문서를 찾지 못했습니다.')
    const body = (await request.json()) as Schemas['DecisionRequest']
    const step = current(doc)
    const via = delegationFor(me, doc)
    if (!step) return problem(409, 'invalid-state', '이미 끝난 결재입니다.')
    if (step.approverId !== me.id && !via) return problem(403, 'not-current-approver', '지금 결재할 차례가 아닙니다.')
    if (body.version !== doc.version) {
      return problem(409, 'version-conflict', '다른 사람이 먼저 바꿨습니다. 새로 불러온 내용을 확인해 주세요.')
    }
    const before = { status: doc.status, currentStep: doc.currentStep }
    Object.assign(step, {
      status: kind === 'approve' ? 'approved' : 'rejected',
      actedBy: me.id,
      onBehalfOf: via ? via.delegatorId : null,
      delegationId: via?.id ?? null,
      actedAt: new Date().toISOString(),
      comment: body.comment ?? null,
    })
    if (kind === 'reject') {
      doc.status = 'rejected'
      doc.currentStep = null
    } else {
      const next = doc.steps.find((s) => s.order === step.order + 1)
      if (next) {
        next.status = 'pending'
        doc.currentStep = next.order
      } else {
        doc.status = 'approved'
        doc.currentStep = null
      }
    }
    doc.version++
    const result: Schemas['ActionResult'] = {
      actionId: `act-inbox-${++idSeq}`,
      operation: kind === 'approve' ? 'approveDocument' : 'rejectDocument',
      summary: `${doc.title}을 ${kind === 'approve' ? '승인' : '반려'}했습니다.`,
      changes: [
        { op: 'update', resource: 'approval_document', resourceId: doc.id, before, after: { status: doc.status, currentStep: doc.currentStep } },
      ],
      undoable: false,
      resource: structuredClone(doc),
    }
    return HttpResponse.json(result, { status: 201 })
  })
}

export const inboxHandlers = [
  http.get(api('/employees'), ({ request }) => {
    if (!employeeForToken(request.headers.get('Authorization'))) return unauthorized()
    const url = new URL(request.url)
    const q = url.searchParams.get('q') ?? ''
    const unitId = url.searchParams.get('unitId')
    const limit = Number(url.searchParams.get('limit') ?? 20)
    const items: Schemas['EmployeeSummary'][] = Object.entries(directory)
      .filter(([, e]) => e.name.includes(q) && (!unitId || e.unitId === unitId))
      .slice(0, limit)
      .map(([id, e]) => ({ id, name: e.name, unitId: e.unitId, unitName: e.unitName, grade: e.grade }))
    return HttpResponse.json({ items })
  }),

  http.get(api('/approval-forms'), ({ request }) => {
    if (!employeeForToken(request.headers.get('Authorization'))) return unauthorized()
    const items: Schemas['ApprovalForm'][] = Object.entries(FORMS).map(([id, name]) => ({
      id,
      name,
      fieldsSchema: id === 'leave' ? LEAVE_SCHEMA : id === 'expense' ? EXPENSE_SCHEMA : {},
      amountField: id === 'leave' ? null : 'amount',
    }))
    return HttpResponse.json({ items })
  }),

  http.get(api('/inbox'), ({ request }) => {
    const me = employeeForToken(request.headers.get('Authorization'))
    if (!me) return unauthorized()
    const box = new URL(request.url).searchParams.get('box') ?? ''
    if (!['inbox', 'delegated', 'done', 'outbox'].includes(box)) return problem(400, 'validation', 'box 값이 올바르지 않습니다.')
    const items = docs
      .filter((d) => inBox(me, d, box))
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
      .map((d) => view(me, d))
    return HttpResponse.json({ items })
  }),

  // 알림(툴바 종 모양): 내 결재 차례인 문서마다 하나. 모의 서버는 읽음 상태를 두지 않습니다
  http.get(api('/notifications'), ({ request }) => {
    const me = employeeForToken(request.headers.get('Authorization'))
    if (!me) return unauthorized()
    const items: Schemas['Notification'][] = docs
      .filter((d) => inBox(me, d, 'inbox'))
      .map((d) => ({ id: `ntf-${d.id}`, kind: 'approval_turn', message: `${d.title} 결재 차례입니다.`, documentId: d.id, createdAt: d.createdAt, read: false }))
    return HttpResponse.json({ items })
  }),

  http.get(api('/inbox/:id'), ({ request, params }) => {
    const me = employeeForToken(request.headers.get('Authorization'))
    if (!me) return unauthorized()
    const doc = docs.find((d) => d.id === params.id)
    return doc ? HttpResponse.json(view(me, doc)) : problem(404, 'not-found', '결재 문서를 찾지 못했습니다.')
  }),

  decide('approve'),
  decide('reject'),

  http.get(api('/delegations'), ({ request }) => {
    const me = employeeForToken(request.headers.get('Authorization'))
    if (!me) return unauthorized()
    const role = new URL(request.url).searchParams.get('role')
    const items = delegations
      .filter(
        (d) =>
          (role !== 'delegate' && d.delegatorId === me.id) || (role !== 'delegator' && d.delegateId === me.id),
      )
      .map(delegationView)
    return HttpResponse.json({ items })
  }),

  http.post(api('/delegations'), async ({ request }) => {
    const me = employeeForToken(request.headers.get('Authorization'))
    if (!me) return unauthorized()
    const dryRun = new URL(request.url).searchParams.get('dryRun') === 'true'
    if (!dryRun && !hasKey(request)) return keyRequired()
    const body = (await request.json()) as Schemas['DelegationCreate']
    if (body.delegateId === me.id) return problem(422, 'delegation-self', '자기 자신에게는 위임할 수 없습니다.')
    if (!directory[body.delegateId]) return problem(422, 'validation', '대리인을 찾지 못했습니다.')
    if (Date.parse(body.endsAt) <= Date.parse(body.startsAt)) {
      return problem(422, 'validation', '끝 시각은 시작 시각보다 뒤여야 합니다.')
    }
    const draft: Delegation = {
      id: dryRun ? 'preview' : `dlg-${++idSeq + 100}`,
      delegatorId: me.id,
      delegateId: body.delegateId,
      startsAt: body.startsAt,
      endsAt: body.endsAt,
      scope: body.scope,
      reason: body.reason,
      status: 'scheduled',
      registeredBy: me.id,
      revokedAt: null,
      revokedBy: null,
      createdAt: new Date().toISOString(),
    }
    draft.status = delegationStatus(draft)
    const changes: Schemas['Change'][] = [
      {
        op: 'create',
        resource: 'delegation',
        resourceId: dryRun ? null : draft.id,
        before: null,
        after: {
          대리인: nameOf(draft.delegateId),
          시작: draft.startsAt,
          끝: draft.endsAt,
          양식: draft.scope.formTypes.join(', ') === '*' ? '모든 양식' : draft.scope.formTypes.join(', '),
          금액한도: draft.scope.maxAmount ?? '없음',
        },
      },
    ]
    const summary = `${nameOf(draft.delegateId)}에게 결재를 위임합니다.`
    if (dryRun) {
      const preview: Schemas['WritePreview'] = { dryRun: true, operation: 'createDelegation', summary, changes, undoable: true }
      return HttpResponse.json(preview)
    }
    delegations.push(draft)
    const result: Schemas['ActionResult'] = {
      actionId: `act-dlg-${idSeq}`,
      operation: 'createDelegation',
      summary,
      changes,
      undoable: true,
      resource: structuredClone(draft),
    }
    return HttpResponse.json(result, { status: 201 })
  }),

  http.post(api('/delegations/:id/revoke'), ({ request, params }) => {
    const me = employeeForToken(request.headers.get('Authorization'))
    if (!me) return unauthorized()
    if (!hasKey(request)) return keyRequired()
    const d = delegations.find((x) => x.id === params.id)
    if (!d) return problem(404, 'delegation-not-found', '위임을 찾지 못했습니다.')
    if (d.delegatorId !== me.id) return problem(403, 'forbidden', '본인이 맡긴 위임만 해지할 수 있습니다.')
    const status = delegationStatus(d)
    if (status === 'revoked' || status === 'expired') return problem(409, 'delegation-revoked', '이미 끝난 위임입니다.')
    d.revokedAt = new Date().toISOString()
    d.revokedBy = me.id
    const result: Schemas['ActionResult'] = {
      actionId: `act-revoke-${++idSeq}`,
      operation: 'revokeDelegation',
      summary: `${nameOf(d.delegateId)}에게 맡긴 위임을 해지했습니다.`,
      changes: [{ op: 'update', resource: 'delegation', resourceId: d.id, before: { status }, after: { status: 'revoked' } }],
      undoable: false,
      resource: delegationView(d),
    }
    return HttpResponse.json(result, { status: 201 })
  }),
]
