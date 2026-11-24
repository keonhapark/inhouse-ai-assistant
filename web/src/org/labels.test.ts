import { describe, expect, it } from 'vitest'
import { callableByText, gradeName, overrideWhen } from './labels'

describe('labels', () => {
  it('위험 정책 예외 조건', () => {
    expect(overrideWhen({ when: 'wide_scope' })).toBe('범위가 넓을 때')
    expect(overrideWhen({ when: 'always' })).toBe('항상')
    expect(overrideWhen({ when: 'arg_gt', arg: 'amount', gt: 1000000 })).toBe('금액이 1,000,000원보다 클 때')
    expect(overrideWhen({ when: 'arg_gt', arg: 'quantity', gt: 10 })).toBe('수량이 10보다 클 때')
    expect(overrideWhen({ when: 'arg_gt', arg: 'total_amount', gt: 5000000 })).toBe('합계가 5,000,000원보다 클 때')
    expect(overrideWhen({ when: 'arg_gt' })).toBe('값 조건이 맞을 때')
  })

  it('부를 수 있는 사람', () => {
    expect(callableByText('all')).toBe('모든 직원')
    expect(callableByText(undefined)).toBe('정보 없음')
    expect(callableByText({})).toBe('정보 없음')
    expect(callableByText({ roles: ['employee'], grades: ['team_leader'] })).toBe('역할 직원 또는 직급 팀장')
  })

  it('모르는 직급은 id 그대로', () => {
    expect(gradeName('ceo')).toBe('대표이사')
    expect(gradeName('intern')).toBe('intern')
  })
})
