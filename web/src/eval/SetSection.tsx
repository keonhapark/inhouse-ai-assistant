import type { Schemas } from '../api/client'
import { Badge } from '../components/Badge'
import { concernName, conditionName, GROUP, OUTCOME, setName } from './labels'
import { ConditionHead, Diff, Interval, Scroll } from './parts'

type SetSummary = Schemas['setSummary']
const OUTCOME_KEYS = ['incident', 'blocked', 'completed', 'failed'] as const

/** 보고서의 셋 하나(확인·개발·정상). eval/harness/report.py의 절 순서와 같게 그립니다. */
export function SetSection({ s, conditions, passK }: { s: SetSummary; conditions: string[]; passK: number }) {
  const id = `set-${s.set}`
  return (
    <section className="eval__set" aria-labelledby={id}>
      <h2 id={id}>
        {setName(s.set)} {s.main ? <Badge tone="accent">주 결과</Badge> : s.set === 'dev' ? <Badge>개발용 · 주 결과 아님</Badge> : null}
      </h2>
      {s.concern && <ConcernPart c={s.concern} conditions={conditions} main={!!s.main} />}
      {s.normal && <NormalPart n={s.normal} conditions={conditions} passK={passK} />}
      <CommonPart c={s.common} />
    </section>
  )
}

function ConcernPart({ c, conditions, main }: { c: NonNullable<SetSummary['concern']>; conditions: string[]; main: boolean }) {
  // 비교 열은 모든 줄에 나온 (a, b)를 모아 만들고, 칸은 이름으로 찾습니다(줄마다 순서·개수가 달라도 어긋나지 않게).
  const pairs = [...new Map((c.comparisons ?? []).flatMap((r) => r.diffs.map((d) => [`${d.a}-${d.b}`, [d.a, d.b] as const]))).values()]
  return (
    <>
      <h3>우려 시나리오</h3>
      {c.full && (
        <>
          <h4>{main ? '주 지표' : '사고'}: 이 프로젝트 우려 유형별 사고</h4>
          <p className="muted">시나리오 단위 n/N(비율, Clopper-Pearson 95% 구간)과 회차 단위 n/N(보조)입니다.</p>
          <Scroll label="유형별 사고 표">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">유형</th>
                  <th scope="col">시나리오 단위</th>
                  <th scope="col">회차 단위</th>
                </tr>
              </thead>
              <tbody>
                {c.full.map((r) => (
                  <tr key={r.concernType ?? 'all'}>
                    <th scope="row">{concernName(r.concernType)}</th>
                    <td>
                      <Interval p={r.scenarios} />
                    </td>
                    <td>
                      {r.runs.n}/{r.runs.N}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
        </>
      )}
      <h4>조건별 사고(시나리오 단위)</h4>
      <Scroll label="조건별 사고 표">
        <table className="table">
          <ConditionHead first="유형" conditions={conditions} />
          <tbody>
            {c.byCondition.map((r) => (
              <tr key={r.concernType ?? 'all'}>
                <th scope="row">{concernName(r.concernType)}</th>
                {conditions.map((cond) => {
                  const cell = r.cells.find((x) => x.condition === cond)
                  return <td key={cond}>{cell ? `${cell.n}/${cell.N}` : '-'}</td>
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
      {!!c.comparisons?.length && (
        <>
          <h4>{main ? '주 비교' : '비교'}: 사고율 차이(이 프로젝트 − 비교 조건)</h4>
          <p className="muted">같은 시나리오끼리 짝지은 차이와 Newcombe 95% 구간입니다. 음수면 이 프로젝트의 사고가 적습니다.</p>
          <Scroll label="사고율 차이 표">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">유형</th>
                  {pairs.map(([a, b]) => (
                    <th scope="col" key={`${a}-${b}`}>
                      {conditionName(a)} − {conditionName(b)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {c.comparisons.map((r) => (
                  <tr key={r.concernType ?? 'all'}>
                    <th scope="row">{concernName(r.concernType)}</th>
                    {pairs.map(([a, b]) => (
                      <td key={`${a}-${b}`}>
                        <Diff d={r.diffs.find((d) => d.a === a && d.b === b)} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
        </>
      )}
      {!!c.byAuthor?.length && (
        <>
          <h4>작성자별 사고(시나리오 단위)</h4>
          <Scroll label="작성자별 사고 표">
            <table className="table">
              <ConditionHead first="작성자" conditions={conditions} />
              <tbody>
                {c.byAuthor.map((r) => (
                  <tr key={r.author}>
                    <th scope="row">{r.author}</th>
                    {conditions.map((cond) => {
                      const cell = r.cells.find((x) => x.condition === cond)
                      return <td key={cond}>{cell ? `${cell.n}/${cell.N}` : '-'}</td>
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
        </>
      )}
      <h4>결과 분포(회차 단위)와 실행 후 취소 건수</h4>
      <Scroll label="결과 분포 표">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">조건</th>
              {OUTCOME_KEYS.map((o) => (
                <th scope="col" className="num" key={o}>
                  {OUTCOME[o].label}
                </th>
              ))}
              <th scope="col" className="num">
                실행 후 취소됨
              </th>
              <th scope="col" className="num">
                막힌 금지 도구 시도
              </th>
            </tr>
          </thead>
          <tbody>
            {c.outcomes.map((r) => (
              <tr key={r.condition}>
                <th scope="row">{conditionName(r.condition)}</th>
                {OUTCOME_KEYS.map((o) => (
                  <td className="num" key={o}>
                    {r[o]}
                  </td>
                ))}
                <td className="num">{r.executedThenUndone ?? '-'}</td>
                <td className="num">{r.forbiddenAttempts ?? '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
    </>
  )
}

function NormalPart({ n, conditions, passK }: { n: NonNullable<SetSummary['normal']>; conditions: string[]; passK: number }) {
  const v = n.fullVsNoGuard
  return (
    <>
      <h3>정상 시나리오</h3>
      <h4>보호 지표: pass^{passK}</h4>
      <p className="muted">시나리오 하나가 {passK}회 모두 정상 완료일 때만 통과입니다.</p>
      <Scroll label="보호 지표 표">
        <table className="table">
          <ConditionHead first="구분" conditions={conditions} />
          <tbody>
            {n.passK.map((r) => (
              <tr key={r.group}>
                <th scope="row">{GROUP[r.group] ?? r.group}</th>
                {conditions.map((cond) => (
                  <td key={cond}>
                    <Interval p={r.cells.find((x) => x.condition === cond)?.rate} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
      <ul className="eval__findings">
        {n.fullVsWriteBlocked && (
          <li>
            이 프로젝트 대 쓰기 차단: 처리한 업무(pass^{passK}) {n.fullVsWriteBlocked.full}개 대 {n.fullVsWriteBlocked.writeBlocked}개, 차이{' '}
            {n.fullVsWriteBlocked.full - n.fullVsWriteBlocked.writeBlocked >= 0 ? '+' : ''}
            {n.fullVsWriteBlocked.full - n.fullVsWriteBlocked.writeBlocked}개
          </li>
        )}
        {v && (
          <li>
            이 프로젝트 대 장치 없음: <Diff d={v.diff} />{' '}
            {v.verdict === 'mostly_not_blocked' ? (
              <Badge tone="success">정상 업무 거의 안 막음</Badge>
            ) : (
              <Badge>판단 못 함</Badge>
            )}
            <div className="muted">구간 하한이 -10%p보다 위일 때만 "정상 업무 거의 안 막음"으로 씁니다.</div>
          </li>
        )}
      </ul>
      <h4>라우터(보조): 정답 에이전트로 넘긴 비율(회차 단위)</h4>
      <Scroll label="라우터 표">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">조건</th>
              <th scope="col">LLM 라우터</th>
            </tr>
          </thead>
          <tbody>
            {n.router.map((r) => (
              <tr key={r.condition}>
                <th scope="row">{conditionName(r.condition)}</th>
                <td>
                  <Interval p={r.rate} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
    </>
  )
}

function CommonPart({ c }: { c: SetSummary['common'] }) {
  const sec = (v: number | null | undefined) => (v == null ? '-' : `${v.toFixed(1)}초`)
  return (
    <>
      <h3>실행 전 확인 요청(회차 합계)</h3>
      <Scroll label="실행 전 확인 요청 표">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">조건</th>
              <th scope="col" className="num">
                실행 전 확인 요청
              </th>
              <th scope="col" className="num">
                놓친 위험
              </th>
              <th scope="col" className="num">
                불필요한 확인
              </th>
            </tr>
          </thead>
          <tbody>
            {c.approvals.map((r) => (
              <tr key={r.condition}>
                <th scope="row">{conditionName(r.condition)}</th>
                <td className="num">{r.requested}</td>
                <td className="num">{r.missedRisks}</td>
                <td className="num">{r.unnecessary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
      <h3>경로별 결과(회차 단위)</h3>
      <Scroll label="경로별 결과 표">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">조건</th>
              <th scope="col">경로</th>
              {OUTCOME_KEYS.map((o) => (
                <th scope="col" className="num" key={o}>
                  {OUTCOME[o].label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {c.routes.map((r) => (
              <tr key={`${r.condition}-${r.route}`}>
                <th scope="row">{conditionName(r.condition)}</th>
                <td>
                  <code>{r.route}</code>
                </td>
                {OUTCOME_KEYS.map((o) => (
                  <td className="num" key={o}>
                    {r[o]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
      <h3>비용과 지연(회차 단위)</h3>
      <Scroll label="비용과 지연 표">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">조건</th>
              <th scope="col" className="num">
                p50
              </th>
              <th scope="col" className="num">
                p95
              </th>
              <th scope="col" className="num">
                비용(달러)
              </th>
              <th scope="col" className="num">
                비용 정보 없음
              </th>
            </tr>
          </thead>
          <tbody>
            {c.costLatency.map((r) => (
              <tr key={r.condition}>
                <th scope="row">{conditionName(r.condition)}</th>
                <td className="num">{sec(r.p50S)}</td>
                <td className="num">{sec(r.p95S)}</td>
                <td className="num">{r.costUsd == null ? '-' : r.costUsd.toFixed(4)}</td>
                <td className="num">{r.costUnknown}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
    </>
  )
}
