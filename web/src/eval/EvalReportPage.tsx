import { useSearchParams } from 'react-router-dom'
import { api, type Schemas } from '../api/client'
import { Badge } from '../components/Badge'
import { useLoad } from '../admin/load'
import { formatDateTime } from '../inbox/labels'
import { conditionName, setName } from './labels'
import { ScenarioTable } from './ScenarioTable'
import { SetSection } from './SetSection'
import { Toolbar } from '../shell/Toolbar'
import '../admin/admin.css'
import './eval.css'

// openapi-typescript가 JSON Schema의 $defs를 속성으로 옮겨 적어 뺍니다(응답 본문에는 없음).
type Report = Omit<Schemas['report.schema'], '$defs'>

/** 평가 리포트(auditor). eval 하네스가 쓴 보고서 JSON을 gateway로 받아 보여 줍니다. 통계는 보고서 summary의 값을 그대로 씁니다. */
export function EvalReportPage() {
  const [params, setParams] = useSearchParams()
  const list = useLoad('eval-reports', () => api.GET('/eval/reports'), '평가 보고서 목록을 불러오지 못했습니다.')
  const items = list.status === 'ok' ? list.data.items : []
  // 주소의 보고서가 없거나 목록에 없으면 가장 최근 것을 엽니다.
  const reportId = items.find((i) => i.reportId === params.get('report'))?.reportId ?? items[0]?.reportId

  return (
    <main className="admin eval" aria-labelledby="eval-title">
      <Toolbar title="평가 리포트" titleId="eval-title" />
      <div className="admin__body">
      {list.status === 'loading' && <p className="muted">불러오는 중입니다.</p>}
      {list.status === 'error' && <p role="alert">{list.message}</p>}
      {list.status === 'ok' && items.length === 0 && <p className="muted">아직 커밋된 평가 보고서가 없습니다.</p>}
      {items.length > 0 && (
        <label className="admin__field">
          <span>보고서</span>
          <select value={reportId} onChange={(e) => setParams({ report: e.target.value })}>
            {items.map((i) => (
              <option key={i.reportId} value={i.reportId}>
                {i.title ?? i.reportId} · {formatDateTime(i.startedAt)}
                {i.complete ? '' : ' · 일부만 실행'}
              </option>
            ))}
          </select>
        </label>
      )}
      {reportId && <ReportView key={reportId} reportId={reportId} />}
      </div>
    </main>
  )
}

function ReportView({ reportId }: { reportId: string }) {
  const state = useLoad<Report>(
    reportId,
    () => api.GET('/eval/reports/{reportId}', { params: { path: { reportId } } }) as Promise<{ data?: Report; error?: unknown }>,
    '평가 보고서를 불러오지 못했습니다.',
  )
  if (state.status === 'loading') return <p className="muted">불러오는 중입니다.</p>
  if (state.status === 'error') return <p role="alert">{state.message}</p>
  const { meta, rows, summary } = state.data
  const sets = [...new Set(rows.map((r) => r.set))]

  return (
    <>
      <section aria-labelledby="eval-meta" className="eval__meta">
        <h2 id="eval-meta">실행 조건</h2>
        {!meta.complete && (
          <p role="status" className="alert">
            일부만 실행했습니다({meta.done_runs}/{meta.planned_runs}회차){meta.stopped_reason ? `: ${meta.stopped_reason}` : ''}. 결과를 다른 보고서와 섞어 비교하지 않습니다.
          </p>
        )}
        <dl className="eval__dl">
          <Item label="셋">{sets.map(setName).join(', ')}</Item>
          <Item label="조건">{meta.conditions.map(conditionName).join(', ')}</Item>
          <Item label="반복">{meta.repeats}회</Item>
          <Item label="회차">
            {meta.done_runs}/{meta.planned_runs}
            {meta.retried_runs ? ` (다시 돌림 ${meta.retried_runs})` : ''}
          </Item>
          <Item label="팩">{[meta.pack_version ?? meta.pack, meta.pack_stage != null ? `단계 ${meta.pack_stage}` : null].filter(Boolean).join(', ') || '-'}</Item>
          <Item label="모델(설정)">{meta.model ?? '-'}</Item>
          <Item label="기기">{meta.machine}</Item>
          <Item label="커밋">
            <code title={meta.commit}>{meta.commit.slice(0, 7)}</code>
            {meta.dirty && <Badge tone="warning">커밋 안 한 변경 있음</Badge>}
          </Item>
          <Item label="실행">
            {formatDateTime(meta.started_at)} ~ {meta.finished_at ? formatDateTime(meta.finished_at) : '-'}
          </Item>
          <Item label="비용">
            {meta.cost_spent_usd != null ? `$${meta.cost_spent_usd.toFixed(4)}` : '-'}
            {meta.cost_cap_usd != null ? ` / 상한 $${meta.cost_cap_usd}` : ''}
            {meta.cost_unknown_runs ? ` (비용 모름 ${meta.cost_unknown_runs}회차)` : ''}
          </Item>
        </dl>
        {!!meta.notes?.length && (
          <details className="eval__notes">
            <summary>실행 메모 {meta.notes.length}개</summary>
            <ul>
              {meta.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          </details>
        )}
      </section>

      {summary ? (
        summary.sets.map((s) => <SetSection key={s.set} s={s} conditions={meta.conditions} passK={summary.passK} />)
      ) : (
        <p className="alert">이 보고서에는 요약(summary)이 없어 지표 표를 그리지 않습니다. 저장소의 같은 이름 .md 보고서를 보고, 아래 시나리오별 결과만 확인할 수 있습니다.</p>
      )}

      <ScenarioTable rows={rows} conditions={meta.conditions} />
    </>
  )
}

function Item({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}
