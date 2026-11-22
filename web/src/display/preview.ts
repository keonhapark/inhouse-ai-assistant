/**
 * 실행 미리보기(WritePreview.changes)를 사람이 읽는 줄로 바꿉니다(#556).
 *
 * - 결재 문서는 양식 스키마(GET /approval-forms)의 필드 이름·순서·선택지 이름으로 fields를 펴고, steps는 결재선(순서·이름·직급)으로 만듭니다.
 * - 다른 자원은 erp 필드 이름 사전(names.ts)을 쓰고, 시각·날짜·금액·상태를 한국어로 바꿉니다.
 * - id·버전·만든 시각 같은 관리용 값은 줄에서 빼고, 원래 값은 raw로 따로 돌려줘 화면이 "자세히" 안에 둡니다.
 */
import type { Schemas } from '../api/client'
import { changeRows, type ChangeRow } from '../chat/format'
import { STEP_STATUS } from '../inbox/labels'
import { formatDate, formatDateTime, formatWon, ISO_DATETIME } from './format'
import { enumName, fieldName, gradeName, isMoneyKey, resourceName } from './names'

type Change = Schemas['Change']
type Form = Schemas['ApprovalForm']
type Person = Schemas['EmployeeSummary']
type Prop = { title?: string; type?: string | string[]; format?: string; 'x-labels'?: Record<string, string> }

export type Lookups = { forms?: Form[]; people?: Map<string, Person> }
export type PreviewRow = { key: string; label: string; before?: string; after?: string }
export type LineStep = { order: number; who: string; status: string }
export type PreviewView = { title: string; op: string; rows: PreviewRow[]; line: LineStep[]; raw: ChangeRow[] }

const OP = { create: '새로 만듦', update: '바꿈', delete: '지움' } as const

/** 줄에서 빼는 관리용 값. 원래 값은 raw에 남습니다 */
const META = new Set([
  'id', 'version', 'createdAt', 'updatedAt', 'createdBy', 'requesterId', 'reservedBy', 'registeredBy', 'currentStep',
  'commentCount', 'employeeId', 'ticketId', 'authorId', 'revokedAt', 'revokedBy', 'issuedBy', 'year',
])
const YMD = /^\d{4}-\d{2}-\d{2}$/
/** 값이 직원 ID인 필드. 직원 사전이 있으면 이름·직급·부서로 바꿉니다 */
const PERSON_KEYS = new Set(['approverId', 'actedBy', 'onBehalfOf', 'delegateId', 'delegatorId', 'confirmedBy', 'requesterId', 'createdBy', 'reservedBy'])

export function personText(id: string, people?: Map<string, Person>): string {
  const p = people?.get(id)
  return p ? `${p.name} ${gradeName(p.grade)}(${p.unitName})` : id
}

function scopeText(v: unknown, forms?: Form[]): string | null {
  if (!v || typeof v !== 'object' || !('formTypes' in v)) return null
  const s = v as { formTypes?: string[]; maxAmount?: number | null }
  const types = s.formTypes?.includes('*') ? '모든 양식' : (s.formTypes ?? []).map((id) => forms?.find((f) => f.id === id)?.name ?? id).join(', ')
  return `${types}, ${s.maxAmount == null ? '금액 한도 없음' : `${formatWon(s.maxAmount)} 이하`}`
}

/** 배열: 빈 배열은 "없음", 글자·숫자 배열은 쉼표로, 견적 줄 같은 객체 배열은 "품목 수량개"로 잇습니다 */
function listText(v: unknown): string | null {
  if (!Array.isArray(v)) return null
  if (v.length === 0) return '없음'
  if (v.every((x) => typeof x === 'string' || typeof x === 'number')) return v.join(', ')
  if (!v.every((x) => x && typeof x === 'object')) return null
  return v
    .map((x: Record<string, unknown>) => [x.itemName ?? x.itemCode, x.quantity != null ? `${x.quantity}개` : null].filter((t) => t != null && t !== '').join(' '))
    .join(', ')
}

/** 값 하나를 보여 줄 글로 바꿉니다. prop은 양식 스키마의 그 필드 */
export function valueText(key: string, v: unknown, ctx: Lookups = {}, prop?: Prop): string {
  if (v === null || v === undefined || v === '') return '없음'
  if (typeof v === 'string') {
    const label = prop?.['x-labels']?.[v]
    if (label) return label
    if (prop?.format === 'date' || YMD.test(v)) return formatDate(v)
    if (ISO_DATETIME.test(v)) return formatDateTime(v)
    if (PERSON_KEYS.has(key)) return personText(v, ctx.people)
    if (key === 'formId') return ctx.forms?.find((f) => f.id === v)?.name ?? v
    return enumName(key, v)
  }
  if (typeof v === 'number') return isMoneyKey(key) ? formatWon(v) : v.toLocaleString('ko-KR')
  if (typeof v === 'boolean') return v ? '예' : '아니요'
  return scopeText(v, ctx.forms) ?? listText(v) ?? JSON.stringify(v)
}

function props(form?: Form): Record<string, Prop> {
  return ((form?.fieldsSchema as { properties?: Record<string, Prop> } | undefined)?.properties ?? {}) as Record<string, Prop>
}

/** 결재 문서의 fields를 양식 순서대로 폅니다. 양식의 금액 필드는 원 단위로 씁니다 */
export function formRows(fields: Record<string, unknown>, form: Form | undefined, ctx: Lookups = {}): { key: string; label: string; value: string }[] {
  const p = props(form)
  const keys = [...Object.keys(p).filter((k) => k in fields), ...Object.keys(fields).filter((k) => !(k in p))]
  return keys.map((key) => {
    const prop = p[key]
    const v = fields[key]
    const money = typeof v === 'number' && (key === form?.amountField || isMoneyKey(key))
    return { key, label: prop?.title ?? fieldName(key), value: money ? formatWon(v as number) : valueText(key, v, ctx, prop) }
  })
}

function approvalLine(steps: unknown, people?: Map<string, Person>): LineStep[] {
  if (!Array.isArray(steps)) return []
  return (steps as Schemas['ApprovalStep'][])
    .filter((s) => s && typeof s.approverId === 'string')
    .map((s) => {
      // 대결로 처리한 단계는 실제 처리자를 함께 보입니다
      const proxy = s.actedBy && s.actedBy !== s.approverId ? ` (대결: ${personText(s.actedBy, people)})` : ''
      return { order: s.order, who: personText(s.approverId, people) + proxy, status: STEP_STATUS[s.status]?.label ?? s.status }
    })
}

export function previewView(c: Change, ctx: Lookups = {}): PreviewView {
  const before = (c.before ?? {}) as Record<string, unknown>
  const after = (c.after ?? {}) as Record<string, unknown>
  const main = c.op === 'delete' ? before : after
  const isDoc = c.resource === 'approval_document' || c.resource === 'approval'
  const form = isDoc && typeof main.formId === 'string' ? ctx.forms?.find((f) => f.id === main.formId) : undefined
  const raw = changeRows(c)
  const view: PreviewView = { title: form?.name ?? resourceName(c.resource), op: OP[c.op], rows: [], line: [], raw }

  if (isDoc) view.line = approvalLine(main.steps, ctx.people)

  if (c.op === 'update') {
    const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].filter((k) => !META.has(k) && k !== 'steps')
    for (const k of keys) {
      const b = valueText(k, before[k], ctx)
      const a = valueText(k, after[k], ctx)
      if (b !== a) view.rows.push({ key: k, label: fieldName(k), before: b, after: a })
    }
    return withRaw(view)
  }

  const side = c.op === 'create' ? 'after' : 'before'
  for (const [k, v] of Object.entries(main)) {
    if (META.has(k) || k === 'steps' || (c.op === 'create' && (k === 'status' || v === null || v === undefined))) continue
    if (isDoc && k === 'fields' && v && typeof v === 'object') {
      for (const r of formRows(v as Record<string, unknown>, form, ctx)) view.rows.push({ key: `fields.${r.key}`, label: r.label, [side]: r.value })
      continue
    }
    // 양식 필드에 금액이 있으면 문서의 amount는 같은 값이라 뺍니다
    if (isDoc && k === 'amount' && main.fields && typeof main.fields === 'object') continue
    // 양식 이름은 제목으로 보이므로 뺍니다. 양식을 못 불러왔으면 어떤 양식인지 줄로 남깁니다
    if (isDoc && k === 'formId' && form) continue
    // 고객사 이름이 같이 오면 ID는 뺍니다
    if (k === 'customerId' && main.customerName) continue
    view.rows.push({ key: k, label: fieldName(k), [side]: valueText(k, v, ctx) })
  }
  return withRaw(view)
}

/** 보이는 줄이 원래 값과 모두 같으면(빼거나 바꾼 것이 없으면) raw를 비워 같은 내용을 두 번 보이지 않게 합니다 */
function withRaw(v: PreviewView): PreviewView {
  const same = v.raw.length === v.rows.length && v.raw.every((r) => v.rows.some((x) => x.key === r.field && x.label === r.field && x.before === r.before && x.after === r.after))
  return same ? { ...v, raw: [] } : v
}
