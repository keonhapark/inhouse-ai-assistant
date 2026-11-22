import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { LocalBadge, RiskBadge } from './Badge'

describe('RiskBadge', () => {
  it.each([
    ['read', '조회', 'badge--neutral'],
    ['reversible_write', '실행 취소 가능', 'badge--warning'],
    ['irreversible', '실행 취소 불가', 'badge--danger'],
  ] as const)('%s 등급은 "%s"와 %s로 보입니다', (risk, label, cls) => {
    render(<RiskBadge risk={risk} />)
    expect(screen.getByText(label)).toHaveClass('badge', cls)
  })

  it('사내 처리 배지는 local 색을 씁니다', () => {
    render(<LocalBadge />)
    expect(screen.getByText('사내 처리')).toHaveClass('badge--local')
  })
})
