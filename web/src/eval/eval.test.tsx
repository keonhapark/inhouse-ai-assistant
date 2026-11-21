import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { App } from '../App'
import { tokenStore, type Schemas } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'
import { server } from '../mocks/node'
import { diffText, proportionText } from './labels'

function renderAt(path = '/eval', token = 'mock.emp-2008') {
  tokenStore.set(token)
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
  return userEvent.setup()
}

const prop = (n: number, N: number, low: number, high: number) => ({ n, N, rate: n / N, low, high })

/** 우려 셋을 그리는지 보려는 시험용 보고서입니다(실제 실행 결과가 아님). */
type Report = Omit<Schemas['report.schema'], '$defs'>
function concernReport(over: Partial<Schemas['meta']> = {}): Report {
  const conds = ['full', 'approve_all']
  const row = (id: string, condition: string, outcome: Schemas['row']['outcome'], passed: boolean): Schemas['row'] => ({
    scenario_id: id, set: 'confirm', kind: 'leak', concern_type: 'leak', reactive: null, author: 'hand', expected_agent: 'hr',
    condition, repeat: 1, seed: 1, outcome, passed, incidents: outcome === 'incident' ? ['marker_exposed: 표지가 답에 나옴'] : [], shortfalls: [], notes: [],
    route: 'local', routed_agent: 'hr', duration_s: 12.5, cost_usd: 0, error: null,
  })
  return {
    meta: {
      commit: 'abcdef1234567', dirty: false, machine: 'test', started_at: '2026-11-21T10:00:00+09:00', finished_at: '', conditions: conds,
      repeats: 1, planned_runs: 4, done_runs: 4, complete: true, ...over,
    },
    rows: [row('confirm-leak-1', 'full', 'blocked', true), row('confirm-leak-1', 'approve_all', 'incident', false),
      row('confirm-leak-2', 'full', 'blocked', true), row('confirm-leak-2', 'approve_all', 'blocked', true)],
    summary: {
      passK: 1,
      sets: [{
        set: 'confirm', main: true, normal: null,
        concern: {
          full: [{ concernType: 'leak', scenarios: prop(0, 2, 0, 0.842), runs: { n: 0, N: 2 } }, { concernType: null, scenarios: prop(0, 2, 0, 0.842), runs: { n: 0, N: 2 } }],
          byCondition: [{ concernType: null, cells: [{ condition: 'full', n: 0, N: 2 }, { condition: 'approve_all', n: 1, N: 2 }] }],
          comparisons: [{ concernType: null, diffs: [{ a: 'full', b: 'approve_all', pairs: 2, diff: -0.5, low: -0.9, high: 0.2 }] }],
          outcomes: [{ condition: 'full', incident: 0, blocked: 2, completed: 0, failed: 0, executedThenUndone: 0, forbiddenAttempts: 1 }],
        },
        common: { approvals: [], routes: [], costLatency: [] },
      }],
    },
  }
}

const serve = (report: Report) =>
  server.use(
    http.get('*/api/eval/reports', () =>
      HttpResponse.json({ items: [{ reportId: 'r1', title: '시험 보고서', startedAt: '2026-11-21T10:00:00+09:00', conditions: report.meta.conditions, complete: report.meta.complete, hasSummary: !!report.summary }] }),
    ),
    http.get('*/api/eval/reports/r1', () => HttpResponse.json(report)),
  )

describe('평가 리포트', () => {
  it('1단계 정상 셋 보고서: 실행 조건, 보호 지표와 구간, 판정, 라우터를 보여 줍니다', async () => {
    renderAt()
    expect(await screen.findByRole('heading', { name: '실행 조건' })).toBeInTheDocument()
    expect(screen.getByText('240/240')).toBeInTheDocument()
    expect(screen.getByText('실행 메모 9개')).toBeInTheDocument()
    const normal = screen.getByRole('region', { name: '정상 셋' })
    const passTable = within(normal).getByRole('region', { name: '보호 지표 표' })
    expect(within(passTable).getByRole('row', { name: /전체/ })).toHaveTextContent('43/80 (53.8%, 42.2%~65.0%)')
    expect(within(normal).getByText('정상 업무를 거의 막지 않았다')).toBeInTheDocument()
    expect(within(normal).getByText(/\+22\.5%p \(\+12\.2~\+31\.9%p, 짝 80\)/)).toBeInTheDocument()
    expect(within(normal).getByRole('region', { name: '라우터 표' })).toHaveTextContent('71/80 (88.8%, 79.7%~94.7%)')
    expect(screen.getByRole('link', { name: '평가' })).toBeInTheDocument()
  })

  it('시나리오별 결과: 기대와 다른 것만 거르고, 줄을 열어 사고·부족을 봅니다', async () => {
    const user = renderAt()
    const sec = await screen.findByRole('region', { name: '시나리오별 결과' })
    expect(within(sec).getByText(/전체 80개/)).toBeInTheDocument()
    await user.selectOptions(within(sec).getByLabelText('보기'), 'problem')
    const count = Number(within(sec).getByText(/개 시나리오 \/ 전체 80개/).textContent!.match(/^(\d+)/)![1])
    expect(count).toBeGreaterThan(0)
    expect(count).toBeLessThan(80)
    await user.type(within(sec).getByLabelText('시나리오 ID'), 'room-reserve-weekly')
    await user.click(within(sec).getByRole('button', { name: 'normal-room-reserve-weekly' }))
    expect(within(sec).getAllByText(/1회차/).length).toBe(3)
  })

  it('우려 셋: 주 지표, 조건별 사고, 짝 비교 차이를 그립니다', async () => {
    serve(concernReport())
    renderAt()
    const set = await screen.findByRole('region', { name: /확인 셋/ })
    expect(within(set).getByText('주 결과')).toBeInTheDocument()
    expect(within(set).getByRole('region', { name: '유형별 사고 표' })).toHaveTextContent('유출0/2 (0.0%, 0.0%~84.2%)0/2')
    expect(within(set).getByRole('region', { name: '조건별 사고 표' })).toHaveTextContent('합계0/21/2')
    expect(within(set).getByRole('region', { name: '사고율 차이 표' })).toHaveTextContent('-50.0%p (-90.0~+20.0%p, 짝 2)')
  })

  it('일부만 실행했거나 summary가 없으면 알립니다', async () => {
    const r = concernReport({ complete: false, done_runs: 3, stopped_reason: '비용 상한' })
    delete r.summary
    serve(r)
    renderAt()
    expect(await screen.findByRole('status')).toHaveTextContent('일부만 실행했습니다(3/4회차): 비용 상한')
    expect(screen.getByText(/요약\(summary\)이 없어/)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '시나리오별 결과' })).toBeInTheDocument()
  })

  it('auditor가 아니면 메뉴가 없고, 열어도 problem title을 보여 줍니다', async () => {
    renderAt('/eval', 'mock.emp-1001')
    expect(await screen.findByRole('alert')).toHaveTextContent('감사 조회 역할이 필요합니다.')
    expect(screen.queryByRole('link', { name: '평가' })).toBeNull()
  })
})

describe('labels', () => {
  it('비율과 짝 차이 글', () => {
    expect(proportionText({ n: 0, N: 0 })).toBe('-')
    expect(proportionText({ n: 1, N: 4 })).toBe('1/4 (25.0%)')
    expect(diffText({ a: 'full', b: 'no_guard', pairs: 0, diff: 0, low: -1, high: 1 })).toBe('-')
    expect(diffText({ a: 'full', b: 'no_guard', pairs: 10, diff: 0, low: -0.1, high: 0.1 })).toBe('+0.0%p (-10.0~+10.0%p, 짝 10)')
  })
})
