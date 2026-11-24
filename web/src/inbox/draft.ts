import type { Schemas } from '../api/client'

type DelegationCreate = Schemas['DelegationCreate']

/** datetime-local 값(현지 시각) ↔ ISO */
const toIso = (local: string) => new Date(local).toISOString()
function localInput(d: Date) {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}

export type Draft = { delegateId: string; startsAt: string; endsAt: string; formTypes: string[]; maxAmount: string; reason: string }

export function initialDraft(): Draft {
  const start = new Date()
  start.setMinutes(0, 0, 0)
  start.setHours(start.getHours() + 1)
  const end = new Date(start.getTime() + 2 * 86_400_000)
  return { delegateId: '', startsAt: localInput(start), endsAt: localInput(end), formTypes: [], maxAmount: '', reason: '' }
}

/** 서버에 보내기 전에 잡을 수 있는 입력 오류. 없으면 null */
export function checkDraft(d: Draft, now = Date.now()): string | null {
  const start = Date.parse(d.startsAt)
  const end = Date.parse(d.endsAt)
  if (Number.isNaN(start) || Number.isNaN(end)) return '시작과 끝 시각을 넣어 주세요.'
  if (end <= start) return '끝 시각은 시작 시각보다 뒤여야 합니다.'
  if (end <= now) return '이미 지난 기간입니다.'
  if (d.maxAmount !== '' && !(Number.isInteger(Number(d.maxAmount)) && Number(d.maxAmount) >= 0)) {
    return '금액 한도는 0 이상의 정수로 넣어 주세요.'
  }
  return null
}

export function toRequest(d: Draft): DelegationCreate {
  return {
    delegateId: d.delegateId,
    startsAt: toIso(d.startsAt),
    endsAt: toIso(d.endsAt),
    scope: { formTypes: d.formTypes, maxAmount: d.maxAmount === '' ? null : Number(d.maxAmount) },
    reason: d.reason.trim(),
  }
}

/**
 * 확인 시트에 붙일 범위 경고(ux #564 G-1). 모든 양식이나 금액 한도 없음은 대결자가 넓게 대신 결재하게 되므로 한 번 더 알립니다.
 */
export function scopeWarnings(body: DelegationCreate): string[] {
  const out: string[] = []
  if (body.scope.formTypes.includes('*')) out.push('모든 양식을 대신 결재하게 됩니다. 필요한 양식만 고르는 편이 안전합니다.')
  if (body.scope.maxAmount == null) out.push('금액 한도가 없어 금액과 상관없이 대신 결재하게 됩니다.')
  return out
}

/** 대결자가 올린 문서가 지금 내 결재 차례에 있으면, 대결 기간에 그 사람이 자기 문서를 결재하게 된다고 알립니다(ux #564 P-1) */
export function ownDocWarning(name: string, count: number): string | null {
  return count > 0 ? `${name} 님이 올린 문서 ${count}건이 지금 내 결재 차례입니다. 대결 기간에는 ${name} 님이 자기 문서를 결재하게 됩니다.` : null
}
