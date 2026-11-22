import { describe, expect, it } from 'vitest'
import type { Schemas } from '../api/client'
import { conversationMeta } from './conversation'
import { formatDate, formatDateRange, formatDateTime, formatWhen, formatWon } from './format'
import { roleName, toolName } from './names'
import { formRows, previewView } from './preview'

const expense: Schemas['ApprovalForm'] = {
  id: 'expense',
  name: '경비 정산',
  amountField: 'amount',
  fieldsSchema: {
    type: 'object',
    properties: {
      amount: { title: '금액', type: 'integer' },
      spent_on: { title: '사용일', type: 'string', format: 'date' },
      merchant: { title: '가맹점', type: 'string' },
      business_no: { title: '사업자번호', type: 'string' },
      purpose: { title: '목적', type: 'string' },
    },
  },
}
const leave: Schemas['ApprovalForm'] = {
  id: 'leave',
  name: '휴가 신청',
  fieldsSchema: {
    type: 'object',
    properties: {
      leave_type: { title: '종류', type: 'string', 'x-labels': { annual: '연차', half_pm: '오후 반차' } },
      start_date: { title: '시작일', type: 'string', format: 'date' },
      end_date: { title: '종료일', type: 'string', format: 'date' },
      reason: { title: '사유', type: 'string' },
    },
  },
}
const people = new Map([
  ['E0011', { id: 'E0011', name: '나우진', unitId: 'finance', unitName: '재무팀', grade: 'team_leader' }],
  ['E0036', { id: 'E0036', name: '이영수', unitId: 'production-control', unitName: '생산관리팀', grade: 'staff' }],
])

describe('형식', () => {
  it('금액·날짜·기간', () => {
    expect(formatWon(5800)).toBe('5,800원')
    expect(formatWon(null)).toBe('–')
    expect(formatDate('2026-09-30')).toBe('2026. 9. 30.(수)')
    expect(formatDate('9월 30일')).toBe('9월 30일')
    expect(formatDateRange('2026-11-15', '2026-11-21')).toBe('2026. 11. 15.(일) ~ 2026. 11. 21.(토)')
    expect(formatDate('2026-02-30')).toBe('2026-02-30')
    expect(formatDateTime('2026-13-40T25:99Z')).toBe('2026-13-40T25:99Z')
  })

  it('목록의 언제: 오늘·어제·올해·다른 해', () => {
    const now = new Date(2026, 10, 22, 20, 0)
    expect(formatWhen(new Date(2026, 10, 22, 11, 20).toISOString(), now)).toBe('오늘 11:20')
    expect(formatWhen(new Date(2026, 10, 21, 9, 5).toISOString(), now)).toBe('어제 09:05')
    expect(formatWhen(new Date(2026, 10, 3, 9, 5).toISOString(), now)).toBe('11월 3일')
    expect(formatWhen(new Date(2025, 10, 3, 9, 5).toISOString(), now)).toBe('2025. 11. 3.')
  })

  it('도구·역할 이름, 모르면 그대로', () => {
    expect(toolName('expense_request')).toBe('경비 정산 올리기')
    expect(toolName('new_tool')).toBe('new_tool')
    expect(roleName('sales_staff')).toBe('영업 담당')
    expect(roleName('x')).toBe('x')
  })
})

describe('대화 목록', () => {
  it('에이전트·상태·시각으로 같은 제목의 대화를 구별합니다', () => {
    const now = new Date(2026, 10, 22, 20, 0)
    const base = { conversationId: 'c', agentId: 'finance', agentName: '재무', title: '이 영수증으로…', createdAt: new Date(2026, 10, 22, 11, 17).toISOString() }
    expect(conversationMeta({ ...base, status: 'awaiting_approval', updatedAt: new Date(2026, 10, 22, 11, 20).toISOString() }, now)).toBe('재무 · 승인 대기 · 오늘 11:20')
    expect(conversationMeta({ ...base, agentName: null, status: 'active' }, now)).toBe('에이전트 미정 · 오늘 11:17')
  })
})

describe('결재 문서 필드', () => {
  it('양식 순서·이름·선택지 이름과 한국어 날짜로 폅니다', () => {
    expect(formRows({ reason: '병원', end_date: '2026-12-28', leave_type: 'half_pm', start_date: '2026-12-28' }, leave)).toEqual([
      { key: 'leave_type', label: '종류', value: '오후 반차' },
      { key: 'start_date', label: '시작일', value: '2026. 12. 28.(월)' },
      { key: 'end_date', label: '종료일', value: '2026. 12. 28.(월)' },
      { key: 'reason', label: '사유', value: '병원' },
    ])
  })

  it('양식을 모르면 사전 이름이나 키, 금액 키는 원으로', () => {
    expect(formRows({ total_amount: 380000, odd: 'x' }, undefined)).toEqual([
      { key: 'total_amount', label: '합계', value: '380,000원' },
      { key: 'odd', label: 'odd', value: 'x' },
    ])
  })
})

describe('실행 미리보기', () => {
  // #385 실제 확인에서 날값이 그대로 보였던 경비 정산 미리보기(real-chat-attach-receipt.png)
  const doc: Schemas['Change'] = {
    op: 'create',
    resource: 'approval_document',
    resourceId: null,
    after: {
      id: 'doc_9551a0b890f1', formId: 'expense', title: '경비 정산 - 김건우', requesterId: 'E0012', status: 'in_progress',
      fields: { amount: 5800, spent_on: '2026-09-30', merchant: '바른마트 역삼점', purpose: '팀 회의 다과비', business_no: '581-31-95714' },
      amount: 5800,
      steps: [{ order: 1, approverId: 'E0011', status: 'pending', actedBy: null, onBehalfOf: null, delegationId: null, actedAt: null, comment: null }],
      currentStep: 1, version: 1, createdAt: '2026-11-22T02:20:00Z', updatedAt: '2026-11-22T02:20:00Z',
    },
  }

  it('결재 문서: 양식 이름·필드·결재선만 보이고 관리용 값은 raw에만 남깁니다', () => {
    const v = previewView(doc, { forms: [expense], people })
    expect(v.title).toBe('경비 정산')
    expect(v.op).toBe('새로 만듦')
    expect(v.rows.map((r) => [r.label, r.after])).toEqual([
      ['제목', '경비 정산 - 김건우'],
      ['금액', '5,800원'],
      ['사용일', '2026. 9. 30.(수)'],
      ['가맹점', '바른마트 역삼점'],
      ['사업자번호', '581-31-95714'],
      ['목적', '팀 회의 다과비'],
    ])
    expect(v.line).toEqual([{ order: 1, who: '나우진 팀장(재무팀)', status: '결재 차례' }])
    expect(v.raw.map((r) => r.field)).toContain('requesterId')
  })

  it('양식·직원을 못 불러와도 키 대신 사전 이름과 ID로 보여 줍니다', () => {
    const v = previewView(doc)
    expect(v.title).toBe('결재 문서')
    expect(v.rows.find((r) => r.key === 'fields.amount')?.label).toBe('금액')
    expect(v.line[0].who).toBe('E0011')
  })

  it('양식을 모르면 양식 줄을 남기고, 대결로 처리한 단계는 실제 처리자를 보입니다', () => {
    const v = previewView({
      op: 'create', resource: 'approval_document',
      after: { formId: 'expense', fields: { amount: 1 }, steps: [{ order: 1, approverId: 'E0011', status: 'approved', actedBy: 'E0036', onBehalfOf: 'E0011' }] },
    }, { people })
    expect(v.rows.find((r) => r.key === 'formId')?.after).toBe('expense')
    expect(v.line[0].who).toBe('나우진 팀장(재무팀) (대결: 이영수 팀원(생산관리팀))')
  })

  it('견적: 고객사 이름이 있으면 ID는 빼고, 품목 줄은 "품목 수량개"로', () => {
    const v = previewView({
      op: 'create', resource: 'quote',
      after: { customerId: 'cus_0001', customerName: '가온테크(가상)', lines: [{ itemName: '평기어', quantity: 500 }, { itemCode: 'NUT-M8', quantity: null }], totalAmount: 13750000, note: null },
    })
    expect(v.rows.map((r) => [r.label, r.after])).toEqual([
      ['고객사', '가온테크(가상)'],
      ['품목 줄', '평기어 500개, NUT-M8'],
      ['합계', '13,750,000원'],
    ])
  })

  it('보이는 줄이 원래 값과 같으면 "자세히"(raw)를 비우고, 이름을 바꾼 줄이 있으면 남깁니다', () => {
    expect(previewView({ op: 'create', resource: 'delegation', after: { 양식: '모든 양식', 금액한도: '없음' } }).raw).toEqual([])
    expect(previewView({ op: 'create', resource: 'ticket', after: { title: 'VPN', priority: 'high' } }).raw).toHaveLength(2)
  })

  it('바꿈: 바뀐 값만 상태 이름으로 "전 → 후"', () => {
    const v = previewView({ op: 'update', resource: 'approval', resourceId: 'APR-0042', before: { status: 'in_progress', version: 1 }, after: { status: 'withdrawn', version: 2 } })
    expect(v.rows).toEqual([{ key: 'status', label: '상태', before: '진행', after: '회수' }])
  })

  it('불량 보고서·회의실 예약·대결: 사전 이름, 열거값, 시각, 사람 이름, 범위', () => {
    const d = previewView({ op: 'create', resource: 'defect_report', after: { id: 'dfr_1', createdBy: 'E0039', itemCode: 'BRG-6204', severity: 'minor', quantity: 5, lotNo: 'LOT-2611-07', status: 'draft', version: 0, confirmedBy: null } })
    expect(d.title).toBe('불량 보고서')
    expect(d.rows.map((r) => [r.label, r.after])).toEqual([
      ['품목 코드', 'BRG-6204'],
      ['심각도', '경미'],
      ['수량', '5'],
      ['로트 번호', 'LOT-2611-07'],
    ])
    const r = previewView({ op: 'delete', resource: 'room_reservation', before: { id: 'r1', roomId: 'room-c', startsAt: '2026-11-25T06:00:00Z', status: 'confirmed' } })
    expect(r.op).toBe('지움')
    expect(r.rows.find((x) => x.key === 'status')?.before).toBe('확정')
    expect(r.rows.find((x) => x.key === 'startsAt')?.before).toMatch(/^2026\. 11\. 25\. \d{2}:00$/)
    const g = previewView(
      { op: 'create', resource: 'delegation', after: { delegateId: 'E0036', startsAt: '2026-11-23T12:00:00+09:00', scope: { formTypes: ['leave'], maxAmount: null } } },
      { forms: [leave], people },
    )
    expect(g.rows.map((x) => [x.label, x.after])).toEqual([
      ['대결자', '이영수 팀원(생산관리팀)'],
      ['시작', expect.stringMatching(/^2026\. 11\. 23\./)],
      ['범위', '휴가 신청, 금액 한도 없음'],
    ])
  })
})
