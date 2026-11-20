import { describe, expect, it } from 'vitest'
import { checkDraft, toRequest, type Draft } from './draft'

const base: Draft = {
  delegateId: 'emp-1001',
  startsAt: '2026-11-21T09:00',
  endsAt: '2026-11-23T18:00',
  formTypes: ['*'],
  maxAmount: '',
  reason: ' 출장 ',
}
const now = Date.parse('2026-11-20T00:00:00Z')

describe('대결 입력 검사', () => {
  it('맞는 입력은 통과합니다', () => {
    expect(checkDraft(base, now)).toBeNull()
  })

  it.each([
    [{ endsAt: '2026-11-21T09:00' }, '끝 시각은 시작 시각보다 뒤여야 합니다.'],
    [{ startsAt: '2026-11-01T09:00', endsAt: '2026-11-02T09:00' }, '이미 지난 기간입니다.'],
    [{ maxAmount: '1.5' }, '금액 한도는 0 이상의 정수로 넣어 주세요.'],
    [{ maxAmount: '-1' }, '금액 한도는 0 이상의 정수로 넣어 주세요.'],
    [{ startsAt: '' }, '시작과 끝 시각을 넣어 주세요.'],
  ])('%o → %s', (patch, message) => {
    expect(checkDraft({ ...base, ...patch }, now)).toBe(message)
  })
})

describe('toRequest', () => {
  it('현지 시각을 ISO로, 빈 금액 한도를 null로, 사유 앞뒤 공백을 지웁니다', () => {
    const r = toRequest(base)
    expect(r.startsAt).toBe(new Date('2026-11-21T09:00').toISOString())
    expect(r.scope).toEqual({ formTypes: ['*'], maxAmount: null })
    expect(r.reason).toBe('출장')
  })
})
