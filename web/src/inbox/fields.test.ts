import { describe, expect, it } from 'vitest'
import { fieldRows } from './fields'

const leave = {
  id: 'leave',
  name: '휴가 신청',
  fieldsSchema: {
    type: 'object',
    properties: {
      leave_type: { type: 'string', enum: ['annual', 'half_pm'], 'x-labels': { annual: '연차', half_pm: '오후 반차' } },
      start_date: { type: 'string', format: 'date', title: '시작일' },
      reason: { type: 'string' },
    },
  },
}

describe('fieldRows', () => {
  it('title과 x-labels로 이름·값을 바꾸고, 없으면 키와 원래 값을 씁니다', () => {
    expect(fieldRows({ reason: '병원', start_date: '2026-12-28', leave_type: 'half_pm', extra: 3 }, leave)).toEqual([
      { key: 'leave_type', label: 'leave_type', value: '오후 반차' },
      { key: 'start_date', label: '시작일', value: '2026-12-28' },
      { key: 'reason', label: 'reason', value: '병원' },
      { key: 'extra', label: 'extra', value: '3' },
    ])
  })

  it('양식을 모르면 키와 값을 그대로 보여 줍니다', () => {
    expect(fieldRows({ a: null }, undefined)).toEqual([{ key: 'a', label: 'a', value: '–' }])
  })
})
