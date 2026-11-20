import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { tokenStore } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'
import { server } from '../mocks/node'

// 권나래(emp-2008)는 auditor 역할이 있는 모의 직원입니다. 모의 데이터는 src/mocks/admin.ts입니다.
function renderAdmin(token = 'mock.emp-2008') {
  tokenStore.set(token)
  render(
    <MemoryRouter initialEntries={['/admin']}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
  return userEvent.setup()
}

describe('관리자 콘솔', () => {
  it('운영 지표: 합계, 에이전트별 표, 차단 이유, 라우팅, 비용 상한', async () => {
    renderAdmin()
    expect(await screen.findByText('에이전트 실행')).toBeInTheDocument()
    const agents = screen.getByRole('region', { name: '에이전트별' })
    const hr = within(agents).getByRole('row', { name: /인사/ })
    expect(hr).toHaveTextContent('0% (외부 0 · 로컬 96)')
    expect(within(screen.getByRole('region', { name: '차단 이유' })).getByText('위험 정책 거절')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: '입구 라우팅' })).getByText('모델이 고름')).toBeInTheDocument()
    const budgets = screen.getByRole('region', { name: '외부 비용 상한' })
    expect(within(budgets).getByRole('row', { name: /구매자재/ })).toHaveTextContent('상한 넘음 · 로컬로 내림')
    expect(screen.getByRole('link', { name: '관리' })).toBeInTheDocument()
  })

  it('기간을 바꾸면 그 기간으로 다시 부릅니다', async () => {
    const spans: number[] = []
    server.use(
      http.get('*/api/ops/metrics', ({ request }) => {
        const u = new URL(request.url)
        spans.push(Date.parse(u.searchParams.get('until')!) - Date.parse(u.searchParams.get('since')!))
        return undefined
      }),
    )
    const user = renderAdmin()
    await screen.findByText('에이전트 실행')
    await user.click(screen.getByRole('button', { name: '최근 7일' }))
    expect(screen.getByRole('button', { name: '최근 7일' })).toHaveAttribute('aria-pressed', 'true')
    await screen.findByText('에이전트 실행')
    await vi.waitFor(() => expect(spans).toEqual([24 * 3_600_000, 7 * 24 * 3_600_000]))
  })

  it('시작 날짜가 끝 날짜보다 늦으면 알립니다', async () => {
    const user = renderAdmin()
    await screen.findByText('에이전트 실행')
    fireEvent.change(screen.getByLabelText('끝'), { target: { value: '2026-01-01' } })
    fireEvent.change(screen.getByLabelText('시작'), { target: { value: '2026-01-02' } })
    await user.click(screen.getByRole('button', { name: '날짜로 보기' }))
    expect(screen.getByRole('alert')).toHaveTextContent('시작 날짜가 끝 날짜보다 늦거나 비었습니다.')
  })

  it('외부 전송 기록: 가린 자리를 표시하고 에이전트로 거릅니다', async () => {
    const user = renderAdmin()
    await user.click(await screen.findByRole('tab', { name: '외부 전송 기록' }))
    const first = (await screen.findAllByRole('listitem'))[0]
    expect(first).toHaveTextContent('가림 1곳: 전화번호')
    await user.click(within(first).getByText('전사 비서'))
    const mark = within(first).getByTitle('가림: 전화번호')
    expect(mark.tagName).toBe('MARK')
    expect(mark).toHaveTextContent('[전화번호]')

    await user.selectOptions(await screen.findByLabelText('에이전트'), 'procurement')
    await vi.waitFor(() => {
      const items = screen.getAllByRole('listitem').filter((li) => li.classList.contains('egress__item'))
      expect(items.length).toBeGreaterThan(0)
      for (const i of items) expect(i).toHaveTextContent('구매자재')
    })
  })

  it('감사 로그: 20건씩 보고, 더 보기와 종류 필터', async () => {
    const user = renderAdmin()
    await user.click(await screen.findByRole('tab', { name: '감사 로그' }))
    const table = await screen.findByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(21)
    await user.click(screen.getByRole('button', { name: '더 보기' }))
    await vi.waitFor(() => expect(within(screen.getByRole('table')).getAllByRole('row').length).toBeGreaterThan(21))

    await user.selectOptions(screen.getByLabelText('종류'), 'tool.blocked')
    await user.click(screen.getByRole('button', { name: '적용' }))
    await vi.waitFor(() => {
      const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1)
      expect(rows.length).toBeGreaterThan(0)
      for (const r of rows) expect(r).toHaveTextContent('도구 차단')
    })
    expect(screen.getAllByText(/신뢰 등급/).length).toBeGreaterThan(0)
  })

  it('auditor가 아니면 메뉴가 없고, 열어도 problem title을 보여 줍니다', async () => {
    renderAdmin('mock.emp-1001')
    expect(await screen.findByRole('alert')).toHaveTextContent('감사 조회 역할이 필요합니다.')
    expect(screen.queryByRole('link', { name: '관리' })).toBeNull()
  })
})
