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
  return { delegateId: '', startsAt: localInput(start), endsAt: localInput(end), formTypes: ['*'], maxAmount: '', reason: '' }
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
