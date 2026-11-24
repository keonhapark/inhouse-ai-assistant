import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
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

/** 왼쪽 탐색 막대의 운영 묶음에서 화면을 고릅니다 */
async function openMenu(user: ReturnType<typeof userEvent.setup>, name: string) {
  const nav = await screen.findByRole('navigation', { name: '주 메뉴' })
  await user.click(within(nav).getByRole('link', { name }))
}

describe('운영 화면', () => {
  it('운영 지표: 합계, 에이전트별 표, 차단 이유, 라우팅, 비용 상한', async () => {
    renderAdmin()
    expect(await screen.findByText('에이전트 실행')).toBeInTheDocument()
    const agents = screen.getByRole('region', { name: '에이전트별' })
    const hr = within(agents).getByRole('row', { name: /인사/ })
    expect(hr).toHaveTextContent('0% (외부 0 · 사내 96)')
    expect(within(screen.getByRole('region', { name: '차단 이유' })).getByText('정책 차단')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: '에이전트 자동 선택' })).getByText('모델이 고름')).toBeInTheDocument()
    const budgets = screen.getByRole('region', { name: '외부 비용 상한' })
    expect(within(budgets).getByRole('row', { name: /구매자재/ })).toHaveTextContent('상한 넘음 · 사내 모델로 돌림')
    expect(screen.getByRole('link', { name: '운영 지표' })).toHaveAttribute('aria-current', 'page')
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
    // 끝 날짜를 열흘 앞으로 옮겨 시작(엿새 전)보다 앞서게 합니다
    await user.click(screen.getByRole('button', { name: /^끝 / }))
    await screen.findByRole('grid')
    await user.keyboard('{ArrowLeft>10/}{Enter}')
    await user.click(screen.getByRole('button', { name: '날짜로 보기' }))
    expect(screen.getByRole('alert')).toHaveTextContent('시작·끝 날짜를 모두 고르고, 시작을 끝보다 늦지 않게 고르세요.')
  })

  it('외부 전송 기록: 가린 자리를 표시하고 에이전트로 거릅니다', async () => {
    const user = renderAdmin()
    await openMenu(user, '외부 전송 기록')
    const first = (await within(screen.getByRole('main')).findAllByRole('listitem'))[0]
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
    await openMenu(user, '감사 로그')
    const table = await screen.findByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(21)
    // 직원·에이전트·작업은 이름 뒤에 ID를 작게 붙입니다
    const second = within(table).getAllByRole('row')[2]
    await waitFor(() => expect(second).toHaveTextContent('서도윤 emp-2001'))
    expect(second).toHaveTextContent('재무 finance')
    expect(second).toHaveTextContent('결재 회수 approval_withdraw')
    await user.click(screen.getByRole('button', { name: '더 보기' }))
    await vi.waitFor(() => expect(within(screen.getByRole('table')).getAllByRole('row').length).toBeGreaterThan(21))

    await user.selectOptions(screen.getByLabelText('종류'), 'tool.blocked')
    await user.click(screen.getByRole('button', { name: '적용' }))
    await vi.waitFor(() => {
      const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1)
      expect(rows.length).toBeGreaterThan(0)
      for (const r of rows) expect(r).toHaveTextContent('정책 차단')
    })
    expect(screen.getAllByText(/신뢰 등급/).length).toBeGreaterThan(0)
  })

  it('같은 조건으로 돌아오면 예전에 더 보기로 붙인 쪽을 다시 붙이지 않습니다', async () => {
    const user = renderAdmin()
    await openMenu(user, '감사 로그')
    const rows = async () => within(await screen.findByRole('table')).getAllByRole('row').length
    expect(await rows()).toBe(21)
    await user.click(screen.getByRole('button', { name: '더 보기' }))
    await vi.waitFor(async () => expect(await rows()).toBeGreaterThan(21))

    await user.selectOptions(screen.getByLabelText('종류'), 'tool.blocked')
    await user.click(screen.getByRole('button', { name: '적용' }))
    await vi.waitFor(async () => expect(await rows()).toBeLessThan(21))
    await user.click(screen.getByRole('button', { name: '필터 지우기' }))
    await vi.waitFor(async () => expect(await rows()).toBe(21))
  })

  it('더 보기가 실패하면 problem title을 보여 주고 목록은 둡니다', async () => {
    server.use(
      http.get('*/api/audit-events', ({ request }) =>
        new URL(request.url).searchParams.get('cursor')
          ? HttpResponse.json({ type: 'urn:problem:x', title: '감사 저장소가 응답하지 않습니다.', status: 503 }, { status: 503, headers: { 'Content-Type': 'application/problem+json' } })
          : undefined,
      ),
    )
    const user = renderAdmin()
    await openMenu(user, '감사 로그')
    await screen.findByRole('table')
    await user.click(screen.getByRole('button', { name: '더 보기' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('감사 저장소가 응답하지 않습니다.')
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(21)
  })

  it('비용 상한이 없으면 그렇다고 알립니다', async () => {
    server.use(
      http.get('*/api/ops/metrics', () => {
        const zero = { calls: 0, blocked: { total: 0, byCode: {} }, llmRequests: { local: 0, external: 0 }, externalCostUsd: 0 }
        return HttpResponse.json({ since: '2026-11-20T00:00:00Z', until: '2026-11-21T00:00:00Z', totals: zero, agents: [], routing: { total: 0, byMethod: {} }, budgets: null })
      }),
    )
    renderAdmin()
    expect(await screen.findByText('비용 상한을 두지 않았습니다(팩에 budgets.yaml 없음).')).toBeInTheDocument()
    expect(screen.getByText('이 기간에 막은 요청이 없습니다.')).toBeInTheDocument()
  })

  it('상한이 0인 대상은 넘음 대신 외부를 쓰지 않는다고 보여 줍니다', async () => {
    server.use(
      http.get('*/api/ops/metrics', () => {
        const zero = { calls: 0, blocked: { total: 0, byCode: {} }, llmRequests: { local: 0, external: 0 }, externalCostUsd: 0 }
        return HttpResponse.json({
          since: '2026-11-20T00:00:00Z', until: '2026-11-21T00:00:00Z', totals: zero, agents: [], routing: { total: 0, byMethod: {} },
          budgets: { period: 'month', periodStart: '2026-11-01T00:00:00Z', agents: [{ id: 'hr', name: '인사', limitUsd: 0, usedUsd: 0, exceeded: true }], units: [] },
        })
      }),
    )
    renderAdmin()
    const row = await screen.findByRole('row', { name: /인사/ })
    expect(row).toHaveTextContent('상한 0 · 외부 안 씀')
    expect(row).not.toHaveTextContent('상한 넘음')
  })

  it('직원 사전·에이전트 목록을 못 받으면 감사 로그는 ID만 보입니다', async () => {
    server.use(
      http.get('*/api/employees', () => HttpResponse.error()),
      http.get('*/api/agent-registry', () => HttpResponse.error()),
    )
    const user = renderAdmin()
    await openMenu(user, '감사 로그')
    const second = within(await screen.findByRole('table')).getAllByRole('row')[2]
    expect(second).toHaveTextContent('emp-2001')
    expect(second).not.toHaveTextContent('서도윤')
    expect(second).not.toHaveTextContent('재무')
    // 작업 표시 이름은 화면 안의 사전(names.ts)이라 그대로 보입니다
    expect(second).toHaveTextContent('결재 회수 approval_withdraw')
  })

  it('제목은 고른 메뉴 이름이고, 메뉴로 옮겨도 고른 기간을 그대로 둡니다', async () => {
    const user = renderAdmin()
    expect(await screen.findByRole('heading', { level: 1, name: '운영 지표' })).toBeInTheDocument()
    await user.click(within(screen.getByRole('group', { name: '기간' })).getByRole('button', { name: '최근 7일' }))
    await openMenu(user, '감사 로그')
    expect(await screen.findByRole('heading', { level: 1, name: '감사 로그' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '최근 7일' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('보는 기간: 최근 7일')).toBeInTheDocument()
    expect(screen.queryByRole('tablist')).toBeNull()
  })

  it('auditor가 아니면 메뉴가 없고, 주소로 열어도 AI 비서로 보냅니다', async () => {
    renderAdmin('mock.emp-1001')
    const nav = await screen.findByRole('navigation', { name: '주 메뉴' })
    await waitFor(() => expect(within(nav).getByRole('link', { name: 'AI 비서' })).toHaveAttribute('aria-current', 'page'))
    expect(screen.queryByRole('link', { name: '운영 지표' })).toBeNull()
  })
})
