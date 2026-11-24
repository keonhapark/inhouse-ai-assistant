import { describe, expect, it } from 'vitest'
import { addMonths, koDate, koHour, parseYmd, toYmd } from './dates'

describe('날짜 계산', () => {
  it('달을 옮겨도 그 달의 마지막 날을 넘지 않습니다', () => {
    expect(toYmd(addMonths(parseYmd('2026-01-31')!, 1))).toBe('2026-02-28')
    expect(toYmd(addMonths(parseYmd('2028-02-29')!, -12))).toBe('2027-02-28')
    expect(toYmd(addMonths(parseYmd('2026-12-15')!, 1))).toBe('2027-01-15')
  })

  it('넘친 날짜와 잘못된 꼴은 받지 않습니다', () => {
    expect(parseYmd('2026-02-30')).toBeNull()
    expect(parseYmd('11/23/2026')).toBeNull()
    expect(koDate('')).toBe('')
  })

  it('날짜·시각 값의 앞 날짜만 읽습니다', () => {
    expect(koDate('2026-11-23T09:00')).toBe('2026. 11. 23.(월)')
  })

  it('시는 오전·오후 12시간제로 보입니다(0시는 오전 12시, 12시는 오후 12시)', () => {
    expect([0, 9, 12, 14, 23].map(koHour)).toEqual(['오전 12시', '오전 9시', '오후 12시', '오후 2시', '오후 11시'])
  })
})
