import { describe, expect, it } from 'vitest'
import { percentText } from './load'
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

describe('segments 경계', () => {
  const r = (start: number, end: number): Redaction => ({ entity: 'EMAIL_ADDRESS', placeholder: '[이메일]', messageIndex: 0, start, end })
  it('빈 범위는 무시하고, 끝에 붙은 가림과 정렬 안 된 입력을 처리합니다', () => {
    const text = 'a[이메일]b[이메일]'
    const out = segments(text, [r(7, 12), r(1, 6), r(3, 3)], 0)
    expect(out.map((s) => [s.text, !!s.redaction])).toEqual([
      ['a', false],
      ['[이메일]', true],
      ['b', false],
      ['[이메일]', true],
    ])
  })
})

describe('percentText', () => {
  it('0보다 크면 0%, 100보다 작으면 100%로 보이지 않습니다', () => {
    expect(percentText(1, 300)).toBe('<1%')
    expect(percentText(299, 300)).toBe('>99%')
    expect(percentText(0, 300)).toBe('0%')
    expect(percentText(300, 300)).toBe('100%')
    expect(percentText(1, 0)).toBe('0%')
  })
})
