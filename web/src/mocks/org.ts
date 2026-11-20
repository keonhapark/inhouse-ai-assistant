import { http, HttpResponse } from 'msw'
import type { Schemas } from '../api/client'
import { directory, employeeForToken } from './data'
import { problem } from './problem'

type Unit = Schemas['Unit']
type Entry = Schemas['AgentRegistryEntry']

// 제조 팩 org.yaml의 부서를 옮겼습니다. 부서장은 모의 직원 목록(directory)에 있는 사람만 적습니다.
const head = (unitId: string, grade: string) =>
  Object.entries(directory).find(([, e]) => e.unitId === unitId && e.grade === grade)?.[0] ?? null

const UNITS: [id: string, name: string, kind: Unit['kind'], parentId: string | null][] = [
  ['ceo-office', '대표이사실', 'division', null],
  ['mgmt', '경영지원본부', 'division', 'ceo-office'],
  ['hr', '인사팀', 'team', 'mgmt'],
  ['finance', '재무팀', 'team', 'mgmt'],
  ['general-affairs', '총무팀', 'team', 'mgmt'],
  ['sales-div', '영업본부', 'division', 'ceo-office'],
  ['sales', '영업팀', 'team', 'sales-div'],
  ['production-div', '생산본부', 'division', 'ceo-office'],
  ['production-control', '생산관리팀', 'team', 'production-div'],
  ['quality', '품질팀', 'team', 'production-div'],
  ['procurement', '구매자재팀', 'team', 'production-div'],
  ['rnd-center', '기술연구소', 'division', 'ceo-office'],
  ['rnd', '연구개발팀', 'team', 'rnd-center'],
  ['it-ops', 'IT운영팀', 'team', 'ceo-office'],
]

export const units: Unit[] = UNITS.map(([id, name, kind, parentId]) => ({
  id,
  name,
  kind,
  parentId,
  headId: head(id, id === 'ceo-office' ? 'ceo' : kind === 'division' ? 'division_head' : 'team_leader'),
}))

const unitName = (id: string) => units.find((u) => u.id === id)?.name ?? null

const tool = (name: string, risk: Entry['tools'][number]['risk']) => ({ name, risk })
const STANDARD = { read: 'auto', reversibleWrite: 'auto_with_undo', irreversible: 'confirm' } as const
const APPROVALS = [tool('approval_list_mine', 'read'), tool('approval_get', 'read'), tool('approval_withdraw', 'irreversible')]

// 제조 팩 agents.yaml을 등록부 형식으로 옮겼습니다(라우팅 예문은 빼는 계약).
export const registry: Entry[] = [
  {
    id: 'assistant',
    name: '전사 비서',
    version: '0.1.0',
    stage: 1,
    ownerUnitId: 'general-affairs',
    ownerUnitName: unitName('general-affairs'),
    description: '공통 규정 질의, 회의실, 일반 안내를 맡고 맞는 부서 에이전트를 안내합니다.',
    callable: true,
    callableBy: { roles: ['employee'] },
    tools: [
      tool('org_search_employees', 'read'),
      tool('room_list_availability', 'read'),
      tool('room_list_my_reservations', 'read'),
      tool('room_reserve', 'reversible_write'),
      tool('room_cancel_reservation', 'reversible_write'),
      tool('policy_search', 'read'),
    ],
    allowedRisk: ['read', 'reversible_write'],
    docScopes: ['public'],
    modelPolicy: { mode: 'external_allowed' },
    riskPolicy: { read: 'auto', reversibleWrite: 'auto_with_undo', irreversible: 'deny' },
    routingKeywords: ['회의실', '예약', '규정', '안내', '어디', '누구'],
  },
  {
    id: 'hr',
    name: '인사',
    version: '0.1.0',
    stage: 1,
    ownerUnitId: 'hr',
    ownerUnitName: unitName('hr'),
    description: '휴가·반차 결재 요청과 회수, 결재 대결 등록·해지 요청, 인사 규정, 본인 휴가 잔여를 맡습니다.',
    callable: true,
    callableBy: { roles: ['employee'] },
    tools: [
      tool('hr_get_my_profile', 'read'),
      tool('leave_get_balance', 'read'),
      tool('leave_request', 'reversible_write'),
      ...APPROVALS,
      tool('delegation_list', 'read'),
      tool('delegation_register', 'reversible_write'),
      tool('delegation_revoke', 'irreversible'),
      tool('org_search_employees', 'read'),
      tool('policy_search', 'read'),
    ],
    allowedRisk: ['read', 'reversible_write', 'irreversible'],
    docScopes: ['public', 'hr-policy', 'hr-restricted'],
    modelPolicy: { mode: 'local_only', reason: '인사 정보는 외부 LLM으로 보내지 않습니다.' },
    riskPolicy: { ...STANDARD, overrides: [{ tool: 'delegation_register', when: 'wide_scope', action: 'confirm' }] },
    routingKeywords: ['휴가', '연차', '반차', '병가', '결재', '대결', '위임', '인사', '잔여'],
  },
  {
    id: 'finance',
    name: '재무',
    version: '0.1.0',
    stage: 2,
    ownerUnitId: 'finance',
    ownerUnitName: unitName('finance'),
    description: '경비 정산 결재 요청과 회수, 재무 규정(여비·경비) 질의를 맡습니다.',
    callable: true,
    callableBy: { roles: ['employee'] },
    tools: [tool('expense_request', 'reversible_write'), ...APPROVALS, tool('policy_search', 'read')],
    allowedRisk: ['read', 'reversible_write', 'irreversible'],
    docScopes: ['public', 'finance-policy'],
    modelPolicy: { mode: 'local_only', reason: '금액·거래처·사업자번호가 든 재무 정보는 외부 LLM으로 보내지 않습니다.' },
    riskPolicy: STANDARD,
    routingKeywords: ['경비', '정산', '영수증', '출장비', '여비', '법인카드', '지출'],
  },
  {
    id: 'procurement',
    name: '구매자재',
    version: '0.1.0',
    stage: 2,
    ownerUnitId: 'procurement',
    ownerUnitName: unitName('procurement'),
    description: '구매 요청 결재와 회수, 구매 절차 질의를 맡습니다.',
    callable: true,
    callableBy: { roles: ['employee'] },
    tools: [tool('purchase_request', 'reversible_write'), ...APPROVALS, tool('policy_search', 'read')],
    allowedRisk: ['read', 'reversible_write', 'irreversible'],
    docScopes: ['public', 'finance-policy'],
    modelPolicy: { mode: 'external_allowed' },
    riskPolicy: STANDARD,
    routingKeywords: ['구매', '발주', '자재', '품목', '단가', '수량', '견적'],
  },
]

const api = (path: string) => `*/api${path}`
const unauthorized = () => problem(401, 'unauthorized', '로그인이 필요합니다.')

export const orgHandlers = [
  http.get(api('/org/units'), ({ request }) => {
    if (!employeeForToken(request.headers.get('Authorization'))) return unauthorized()
    return HttpResponse.json({ items: units })
  }),

  http.get(api('/agent-registry'), ({ request }) => {
    if (!employeeForToken(request.headers.get('Authorization'))) return unauthorized()
    return HttpResponse.json({ fallbackAgentId: 'assistant', items: registry })
  }),
]
