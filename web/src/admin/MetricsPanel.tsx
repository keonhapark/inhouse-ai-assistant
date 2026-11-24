import { api, type Schemas } from '../api/client'
import { Badge } from '../components/Badge'
import type { Range } from './AdminPage'
import { formatUsd, percent, percentText, useLoad } from './load'

type Metrics = Schemas['OpsMetrics']

const BLOCK_CODE: Record<string, string> = {
  agent_not_callable: '사용할 수 없는 에이전트',
  tool_not_allowed: '허용 안 된 도구',
  trust_violation: '신뢰 등급 위반',
  policy_denied: '정책 차단',
  scope_missing: '권한 범위 없음',
  model_policy: '모델 정책',
}

const ROUTE_METHOD: [keyof Metrics['routing']['byMethod'], string][] = [
  ['llm', '모델이 고름'],
  ['keyword', '낱말로 고름'],
  ['explicit', '직원이 고름'],
  ['fallback', '기본 에이전트'],
]

/** 막대 하나. 값은 옆 글자로 읽고, 막대는 크기만 보여 줍니다(색 하나). */
function Bar({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <span className="bar" title={label} aria-hidden="true">
      <span className="bar__fill" style={{ width: `${pct}%` }} />
    </span>
  )
}

export function MetricsPanel({ range }: { range: Range }) {
  const state = useLoad(
    `${range.since}|${range.until}`,
    () => api.GET('/ops/metrics', { params: { query: range } }),
    '운영 지표를 불러오지 못했습니다.',
  )
  if (state.status === 'loading') return <p className="muted">불러오는 중입니다.</p>
  if (state.status === 'error') return <p role="alert" className="alert">{state.message}</p>
  const m = state.data
  const t = m.totals
  const llm = t.llmRequests.local + t.llmRequests.external
  const maxCalls = Math.max(0, ...m.agents.map((a) => a.calls))
  const codes = Object.entries(t.blocked.byCode).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1])

  return (
    <div className="metrics">
      <dl className="tiles">
        <div className="tile">
          <dt>에이전트 실행</dt>
          <dd>{t.calls.toLocaleString('ko-KR')}</dd>
        </div>
        <div className="tile">
          <dt>정책 차단</dt>
          <dd>{t.blocked.total.toLocaleString('ko-KR')}</dd>
        </div>
        <div className="tile">
          <dt>외부 모델 요청</dt>
          <dd>
            {percentText(t.llmRequests.external, llm)} <span className="muted tile__sub">{t.llmRequests.external.toLocaleString('ko-KR')} / {llm.toLocaleString('ko-KR')}건</span>
          </dd>
        </div>
        <div className="tile">
          <dt>외부 비용</dt>
          <dd>
            {formatUsd(t.externalCostUsd)}
            {(t.unpricedRequests ?? 0) > 0 && <span className="muted tile__sub"> 비용 정보 없음 {t.unpricedRequests}건 제외</span>}
          </dd>
        </div>
      </dl>

      <section aria-labelledby="m-agents">
        <h2 id="m-agents">에이전트별</h2>
        <div className="table-scroll" role="region" aria-label="에이전트별 표" tabIndex={0}>
        <table className="table metrics__agents">
          <thead>
            <tr>
              <th scope="col">에이전트</th>
              <th scope="col" className="num">실행</th>
              <th scope="col" className="num">차단</th>
              <th scope="col">외부 모델 비율</th>
              <th scope="col" className="num">외부 비용</th>
            </tr>
          </thead>
          <tbody>
            {m.agents.map((a) => {
              const n = a.llmRequests.local + a.llmRequests.external
              return (
                <tr key={a.agentId}>
                  <th scope="row">{a.agentName}</th>
                  <td className="num">
                    <span className="bar-cell">
                      <Bar value={a.calls} max={maxCalls} label={`실행 ${a.calls}`} />
                      {a.calls.toLocaleString('ko-KR')}
                    </span>
                  </td>
                  <td className="num">{a.blocked.total.toLocaleString('ko-KR')}</td>
                  <td>
                    <span className="bar-cell">
                      <Bar value={a.llmRequests.external} max={n} label={`외부 ${a.llmRequests.external} / 전체 ${n}`} />
                      {n === 0 ? <span className="muted">요청 없음</span> : `${percentText(a.llmRequests.external, n)} (외부 ${a.llmRequests.external} · 사내 ${a.llmRequests.local})`}
                    </span>
                  </td>
                  <td className="num">{formatUsd(a.externalCostUsd)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        </div>
      </section>

      <div className="metrics__pair">
        <section aria-labelledby="m-blocked">
          <h2 id="m-blocked">차단 이유</h2>
          {codes.length === 0 ? (
            <p className="muted">이 기간에 막은 요청이 없습니다.</p>
          ) : (
            <table className="table">
              <tbody>
                {codes.map(([code, n]) => (
                  <tr key={code}>
                    <th scope="row">{BLOCK_CODE[code] ?? code}</th>
                    <td>
                      <span className="bar-cell">
                        <Bar value={n} max={codes[0][1]} label={`${n}건`} />
                        {n}건
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section aria-labelledby="m-routing">
          <h2 id="m-routing">에이전트 자동 선택</h2>
          <table className="table">
            <tbody>
              {ROUTE_METHOD.map(([k, label]) => {
                const n = m.routing.byMethod[k] ?? 0
                return (
                  <tr key={k}>
                    <th scope="row">{label}</th>
                    <td>
                      <span className="bar-cell">
                        <Bar value={n} max={m.routing.total} label={`${n}건`} />
                        {percentText(n, m.routing.total)} ({n}건)
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </section>
      </div>

      <section aria-labelledby="m-budgets">
        <h2 id="m-budgets">외부 비용 상한</h2>
        {!m.budgets ? (
          <p className="muted">비용 상한을 두지 않았습니다(팩에 budgets.yaml 없음).</p>
        ) : (
          <>
            <p className="muted">
              {m.budgets.period === 'month' ? '이번 달' : '오늘'} 누적입니다. 위 기간 필터와 관계없습니다. 상한을 넘으면 다음 요청부터 외부 요청을 사내 모델로 돌립니다.
            </p>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">대상</th>
                  <th scope="col">사용 / 상한</th>
                </tr>
              </thead>
              <tbody>
                {[...m.budgets.agents.map((b) => ({ ...b, kind: '에이전트' })), ...m.budgets.units.map((b) => ({ ...b, kind: '부서' }))].map((b) => (
                  <tr key={`${b.kind}-${b.id}`}>
                    <th scope="row">
                      {b.name ?? b.id} <span className="muted">{b.kind}</span>
                    </th>
                    <td>
                      <span className="bar-cell">
                        <Bar value={b.usedUsd} max={b.limitUsd} label={`${percent(b.usedUsd, b.limitUsd)}%`} />
                        {formatUsd(b.usedUsd)} / {formatUsd(b.limitUsd)}
                        {b.limitUsd === 0 ? (
                          <Badge>상한 0 · 외부 안 씀</Badge>
                        ) : (
                          (b.exceeded || b.usedUsd >= b.limitUsd) && <Badge tone="danger">상한 넘음 · 사내 모델로 돌림</Badge>
                        )}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>
    </div>
  )
}
