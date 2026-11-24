import { Fragment, useMemo, useState } from 'react'
import type { Schemas } from '../api/client'
import { Badge } from '../components/Badge'
import { concernName, conditionName, OUTCOME, setName } from './labels'
import { Scroll } from './parts'

type Row = Schemas['row']
type Scenario = { id: string; set: string; kind: string; concernType?: string | null; reactive?: boolean | null; runs: Row[] }

const PAGE = 50

/** 시나리오별 결과. 한 줄이 시나리오 하나이고, 조건 칸에 회차마다 결과 배지를 둡니다. 줄을 열면 사고·부족·오류를 봅니다. */
export function ScenarioTable({ rows, conditions: declared }: { rows: Row[]; conditions: string[] }) {
  // meta.conditions에 없는 조건의 회차도 칸으로 보여 줍니다(필터는 모든 회차를 봄).
  const conditions = useMemo(() => [...new Set([...declared, ...rows.map((r) => r.condition)])], [declared, rows])
  const sets = useMemo(() => [...new Set(rows.map((r) => r.set))], [rows])
  const [set, setSet] = useState('')
  const [only, setOnly] = useState<'all' | 'problem'>('all')
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const [shown, setShown] = useState(PAGE)

  const scenarios = useMemo(() => {
    const by = new Map<string, Scenario>()
    for (const r of rows) {
      const s = by.get(r.scenario_id) ?? { id: r.scenario_id, set: r.set, kind: r.kind, concernType: r.concern_type, reactive: r.reactive, runs: [] }
      s.runs.push(r)
      by.set(r.scenario_id, s)
    }
    return [...by.values()]
  }, [rows])

  const filtered = scenarios.filter(
    (s) =>
      (!set || s.set === set) &&
      (only === 'all' || s.runs.some((r) => !r.passed)) &&
      (!q.trim() || s.id.toLowerCase().includes(q.trim().toLowerCase())),
  )

  return (
    <section className="eval__scenarios" aria-labelledby="eval-scenarios">
      <h2 id="eval-scenarios">시나리오별 결과</h2>
      <div className="admin__row" role="group" aria-label="시나리오 필터">
        {sets.length > 1 && (
          <label className="admin__field">
            <span className="muted">셋</span>
            <select value={set} onChange={(e) => (setSet(e.target.value), setShown(PAGE))}>
              <option value="">전체</option>
              {sets.map((s) => (
                <option key={s} value={s}>
                  {setName(s)}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="admin__field">
          <span className="muted">보기</span>
          <select value={only} onChange={(e) => (setOnly(e.target.value as 'all' | 'problem'), setShown(PAGE))}>
            <option value="all">전체</option>
            <option value="problem">기대와 다른 회차가 있는 것만</option>
          </select>
        </label>
        <label className="admin__field">
          <span className="muted">시나리오 ID</span>
          <input value={q} onChange={(e) => (setQ(e.target.value), setShown(PAGE))} placeholder="예: room" />
        </label>
      </div>
      <p className="muted">
        {filtered.length}개 시나리오 / 전체 {scenarios.length}개. 배지는 회차마다 하나이고, ≠ 표시(점선 테두리)는 기대(시나리오 expect)와 다른 회차입니다.
      </p>
      {filtered.length === 0 ? (
        <p className="muted">조건에 맞는 시나리오가 없습니다.</p>
      ) : (
        <Scroll label="시나리오별 결과 표">
          <table className="table eval__runs">
            <thead>
              <tr>
                <th scope="col">시나리오</th>
                <th scope="col">종류</th>
                {conditions.map((c) => (
                  <th scope="col" key={c}>
                    {conditionName(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, shown).map((s) => (
                <Fragment key={s.id}>
                  <tr className={open === s.id ? 'is-open' : undefined}>
                    <th scope="row">
                      <button type="button" className="link" aria-expanded={open === s.id} aria-controls={`run-${s.id}`} onClick={() => setOpen(open === s.id ? null : s.id)}>
                        {s.id}
                      </button>
                    </th>
                    <td>
                      {s.kind === 'normal' ? '정상' : concernName(s.concernType)}
                      {s.reactive && <span className="muted"> · 반응형</span>}
                    </td>
                    {conditions.map((c) => (
                      <td key={c}>
                        <span className="eval__badges">
                          {s.runs
                            .filter((r) => r.condition === c)
                            .sort((a, b) => a.repeat - b.repeat)
                            .map((r) => (
                              <span key={r.repeat} className={r.passed ? undefined : 'eval__miss'}>
                                <Badge tone={OUTCOME[r.outcome]?.tone ?? 'neutral'}>
                                  {OUTCOME[r.outcome]?.label ?? r.outcome}
                                  {!r.passed && (
                                    <>
                                      <span aria-hidden="true"> ≠</span>
                                      <span className="visually-hidden">, 기대와 다름</span>
                                    </>
                                  )}
                                </Badge>
                              </span>
                            ))}
                        </span>
                      </td>
                    ))}
                  </tr>
                  {open === s.id && (
                    <tr className="eval__detail" id={`run-${s.id}`}>
                      <td colSpan={2 + conditions.length}>
                        <RunDetails runs={s.runs} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </Scroll>
      )}
      {filtered.length > shown && (
        <button type="button" className="btn btn--secondary" onClick={() => setShown(shown + PAGE)}>
          더 보기({filtered.length - shown}개 남음)
        </button>
      )}
    </section>
  )
}

function RunDetails({ runs }: { runs: Row[] }) {
  return (
    <ul className="eval__run-list">
      {runs.map((r) => (
        <li key={`${r.condition}-${r.repeat}`}>
          <strong>
            {conditionName(r.condition)} {r.repeat}회차
          </strong>{' '}
          <span className="muted">
            경로 {r.route ?? '-'} · 넘긴 에이전트 {r.routed_agent ?? '-'}
            {r.expected_agent ? `(기대 ${r.expected_agent})` : ''} · {r.duration_s != null ? `${r.duration_s.toFixed(1)}초` : '-'}
          </span>
          {[...(r.incidents ?? []).map((t) => ['사고', t]), ...(r.shortfalls ?? []).map((t) => ['부족', t]), ...(r.error ? [['오류', r.error]] : [])].map(
            ([k, t], i) => (
              <div key={i} className="eval__line">
                <span className="muted">{k}</span> {t}
              </div>
            ),
          )}
        </li>
      ))}
    </ul>
  )
}
