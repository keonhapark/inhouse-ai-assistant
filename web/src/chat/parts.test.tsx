import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { PreviewCard } from './parts'

const approval = (over: object = {}) => ({
  approvalId: 'ap-1',
  tool: 'leave_request_withdraw',
  risk: 'irreversible' as const,
  expiresAt: '2026-11-20T10:00:00Z',
  preview: {
    dryRun: true as const,
    operation: 'withdraw',
    summary: '휴가 결재를 회수합니다.',
    changes: [{ op: 'update' as const, resource: 'approval_document', before: { status: 'pending' }, after: { status: 'withdrawn' } }],
    undoable: false,
    warnings: ['회수하면 결재선이 처음부터 다시 시작됩니다.'],
  },
  ...over,
})

describe('PreviewCard', () => {
  it('되돌릴 수 없는 실행은 위험 버튼과 경고 문장으로 보여 줍니다', () => {
    render(<PreviewCard approval={approval()} busy={false} now={Date.parse('2026-11-20T09:55:00Z')} onDecide={vi.fn()} />)
    expect(screen.getByRole('button', { name: '실행' })).toHaveClass('btn--danger')
    expect(screen.getByText('되돌릴 수 없음')).toBeInTheDocument()
    expect(screen.getByText('실행하면 되돌릴 수 없습니다.')).toBeInTheDocument()
    expect(screen.getByText('회수하면 결재선이 처음부터 다시 시작됩니다.')).toBeInTheDocument()
    expect(screen.getByText('pending')).toHaveClass('changes__before')
    expect(screen.getByText('withdrawn')).toBeInTheDocument()
  })

  it('만료되면 실행·취소를 막고 onExpire를 한 번 부릅니다', () => {
    const onExpire = vi.fn()
    render(
      <PreviewCard approval={approval()} busy={false} now={Date.parse('2026-11-20T10:00:01Z')} onDecide={vi.fn()} onExpire={onExpire} />,
    )
    expect(onExpire).toHaveBeenCalledTimes(1)
    expect(screen.getByText('만료됨')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '실행' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '취소' })).toBeDisabled()
  })

  it('결정이 나면 버튼 대신 결과를 보여 줍니다', () => {
    render(<PreviewCard approval={approval()} decision="reject" busy={false} onDecide={vi.fn()} />)
    expect(screen.getByText('취소함')).toBeInTheDocument()
    expect(screen.queryByRole('button')).toBeNull()
  })
})
