import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { App } from '../App'
import { tokenStore, type Schemas } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'
import { server } from '../mocks/node'
import { diffText, proportionText } from './labels'
import stage1 from '../mocks/fixtures/eval-normal-stage1.json'

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
    expect(await screen.findByRole('heading', { level: 1, name: '평가 리포트' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: '실행 조건' })).toBeInTheDocument()
    expect(screen.getByText('240/240')).toBeInTheDocument()
    expect(screen.getByText(`실행 메모 ${stage1.meta.notes.length}개`)).toBeInTheDocument()
    const normal = screen.getByRole('region', { name: '정상 셋' })
    const passTable = within(normal).getByRole('region', { name: '보호 지표 표' })
    expect(within(passTable).getByRole('row', { name: /전체/ })).toHaveTextContent('43/80 (53.8%, 42.2%~65.0%)')
    expect(within(normal).getByText('정상 업무 거의 안 막음')).toBeInTheDocument()
    expect(within(normal).getByText(/\+22\.5%p \(\+12\.2~\+31\.9%p, 짝 80\)/)).toBeInTheDocument()
    expect(within(normal).getByRole('region', { name: '라우터 표' })).toHaveTextContent('71/80 (88.8%, 79.7%~94.7%)')
    expect(screen.getByRole('link', { name: '평가 리포트' })).toHaveAttribute('aria-current', 'page')
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
    // 불러오는 중 안내도 status라, 보고서가 그려진 뒤의 알림을 기다립니다
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('일부만 실행했습니다(3/4회차): 비용 상한'))
    expect(screen.getByText(/요약이 없어/)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '시나리오별 결과' })).toBeInTheDocument()
  })

  it('시나리오는 50개씩 보이고, 필터를 바꾸면 다시 50개부터 봅니다', async () => {
    const user = renderAt()
    const sec = await screen.findByRole('region', { name: '시나리오별 결과' })
    const rows = () => within(within(sec).getByRole('region', { name: '시나리오별 결과 표' })).getAllByRole('row').length - 1
    expect(rows()).toBe(50)
    await user.click(within(sec).getByRole('button', { name: '더 보기(30개 남음)' }))
    expect(rows()).toBe(80)
    await user.selectOptions(within(sec).getByLabelText('보기'), 'problem')
    expect(rows()).toBe(50)
  })

  it('기대와 다른 회차는 배지 이름에 "기대와 다름"이 들어갑니다', async () => {
    const user = renderAt()
    const sec = await screen.findByRole('region', { name: '시나리오별 결과' })
    await user.type(within(sec).getByLabelText('시나리오 ID'), 'normal-room-reserve-weekly')
    const row = within(sec).getByRole('row', { name: /normal-room-reserve-weekly/ })
    expect(row).toHaveTextContent('실패로 끝남 ≠, 기대와 다름')
    expect(within(row).getAllByText(/기대와 다름/)).toHaveLength(1)
  })

  it('보고서를 바꾸면 필터와 펼친 줄을 처음으로 돌리고, 없는 ?report=는 가장 최근 것을 엽니다', async () => {
    const a = concernReport()
    const b = concernReport({ commit: 'bbbbbbb0000000' })
    server.use(
      http.get('*/api/eval/reports', () =>
        HttpResponse.json({ items: ['r1', 'r2'].map((id) => ({ reportId: id, title: `보고서 ${id}`, startedAt: '2026-11-21T10:00:00+09:00', conditions: a.meta.conditions, complete: true, hasSummary: true })) }),
      ),
      http.get('*/api/eval/reports/r1', () => HttpResponse.json(a)),
      http.get('*/api/eval/reports/r2', () => HttpResponse.json(b)),
    )
    const user = renderAt('/eval?report=nope')
    expect(await screen.findByText('abcdef1')).toBeInTheDocument()
    const sec = screen.getByRole('region', { name: '시나리오별 결과' })
    await user.type(within(sec).getByLabelText('시나리오 ID'), 'leak-2')
    await user.click(within(sec).getByRole('button', { name: 'confirm-leak-2' }))
    await user.selectOptions(screen.getByLabelText('보고서'), 'r2')
    expect(await screen.findByText('bbbbbbb')).toBeInTheDocument()
    const sec2 = screen.getByRole('region', { name: '시나리오별 결과' })
    expect(within(sec2).getByLabelText('시나리오 ID')).toHaveValue('')
    expect(within(sec2).getByRole('button', { name: 'confirm-leak-1' })).toHaveAttribute('aria-expanded', 'false')
  })

  it('보고서 본문이 404면 problem title을 보여 줍니다', async () => {
    const r = concernReport()
    serve(r)
    server.use(
      http.get('*/api/eval/reports/r1', () =>
        HttpResponse.json({ type: 'urn:problem:not-found', title: '보고서를 찾지 못했습니다.', status: 404 }, { status: 404, headers: { 'Content-Type': 'application/problem+json' } }),
      ),
    )
    renderAt()
    expect(await screen.findByRole('alert')).toHaveTextContent('보고서를 찾지 못했습니다.')
  })

  it('모르는 조건·결과는 이름 그대로, 비교는 조건 이름으로 칸을 맞춥니다', async () => {
    const r = concernReport()
    r.rows = [...r.rows, { ...r.rows[0], condition: 'new_cond', outcome: 'weird' as never, passed: true }]
    const concern = r.summary!.sets[0].concern!
    concern.comparisons = [
      { concernType: 'leak', diffs: [{ a: 'full', b: 'baseline_tools', pairs: 2, diff: 0.5, low: 0.1, high: 0.9 }] },
      { concernType: null, diffs: [{ a: 'full', b: 'approve_all', pairs: 2, diff: -0.5, low: -0.9, high: 0.2 }] },
    ]
    serve(r)
    renderAt()
    const cmp = await screen.findByRole('region', { name: '사고율 차이 표' })
    const head = within(cmp).getAllByRole('columnheader').map((h) => h.textContent)
    expect(head).toEqual(['유형', '이 프로젝트 − 기성 도구 기본', '이 프로젝트 − 전건 승인'])
    expect(within(cmp).getByRole('row', { name: /합계/ })).toHaveTextContent('합계--50.0%p')
    const sec = screen.getByRole('region', { name: '시나리오별 결과' })
    expect(within(sec).getByRole('columnheader', { name: 'new_cond' })).toBeInTheDocument()
    expect(within(sec).getByText('weird')).toBeInTheDocument()
  })

  it('auditor가 아니면 메뉴가 없고, 주소로 열어도 AI 비서로 보냅니다', async () => {
    renderAt('/eval', 'mock.emp-1001')
    const nav = await screen.findByRole('navigation', { name: '주 메뉴' })
    await waitFor(() => expect(within(nav).getByRole('link', { name: 'AI 비서' })).toHaveAttribute('aria-current', 'page'))
    expect(screen.queryByRole('link', { name: '평가 리포트' })).toBeNull()
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
