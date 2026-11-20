import { describe, expect, it } from 'vitest'
import { toRange } from './period'
import { segments, type Redaction } from './redact'

describe('toRange', () => {
  const now = new Date('2026-11-21T03:00:00Z')
  it('미리 정한 길이', () => {
    expect(toRange({ kind: 'preset', preset: '7d' }, now)).toEqual({ since: '2026-11-14T03:00:00.000Z', until: '2026-11-21T03:00:00.000Z' })
  })
  it('날짜 범위는 끝 날짜를 포함합니다', () => {
    const r = toRange({ kind: 'custom', from: '2026-11-01', to: '2026-11-01' })!
    expect(Date.parse(r.until) - Date.parse(r.since)).toBe(24 * 3_600_000)
    expect(new Date(r.since).getHours()).toBe(0)
  })
  it('빈 날짜나 거꾸로 된 범위는 null', () => {
    expect(toRange({ kind: 'custom', from: '', to: '2026-11-01' })).toBeNull()
    expect(toRange({ kind: 'custom', from: '2026-11-02', to: '2026-11-01' })).toBeNull()
  })
})

describe('segments', () => {
  const r = (start: number, end: number, messageIndex = 0): Redaction => ({ entity: 'KR_PHONE', placeholder: '[전화번호]', messageIndex, start, end })
  const text = '연락처 [전화번호]로 보내 줘'
  it('가린 자리와 나머지로 나눕니다', () => {
    expect(segments(text, [r(4, 10)], 0).map((s) => [s.text, !!s.redaction])).toEqual([
      ['연락처 ', false],
      ['[전화번호]', true],
      ['로 보내 줘', false],
    ])
  })
  it('다른 메시지의 가림, 벗어난 범위, 겹친 범위는 무시하고 글은 그대로 둡니다', () => {
    const out = segments(text, [r(4, 10, 1), r(4, 99), r(4, 10), r(6, 8)], 0)
    expect(out.map((s) => s.text).join('')).toBe(text)
    expect(out.filter((s) => s.redaction)).toHaveLength(1)
  })
})
