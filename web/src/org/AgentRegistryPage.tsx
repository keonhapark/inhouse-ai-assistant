import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { api, problemTitle, type Schemas } from '../api/client'
import { Badge, RiskBadge, type Risk } from '../components/Badge'
import { Card } from '../components/Card'
import { callableByText, overrideWhen, RISK_ACTION } from './labels'
import '../inbox/inbox.css'
import './org.css'

type Entry = Schemas['AgentRegistryEntry']
type State = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ok'; items: Entry[]; fallbackAgentId?: string }

export function AgentRegistryPage() {
  const [state, setState] = useState<State>({ status: 'loading' })
  const { hash } = useLocation()

  useEffect(() => {
    let alive = true
    api.GET('/agent-registry').then(
      ({ data, error }) =>
        alive &&
        setState(
          data
            ? { status: 'ok', items: data.items, fallbackAgentId: data.fallbackAgentId }
            : { status: 'error', message: problemTitle(error, '에이전트 등록부를 불러오지 못했습니다.') },
        ),
      () => alive && setState({ status: 'error', message: '서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.' }),
    )
    return () => {
      alive = false
    }
  }, [])

  // 조직도에서 #agent-<id>로 들어오면 그 카드로 옮깁니다.
  useEffect(() => {
    if (state.status === 'ok' && hash) document.getElementById(hash.slice(1))?.scrollIntoView?.({ block: 'start' })
  }, [state.status, hash])

  return (
    <main className="registry">
      <h1 className="org__title">에이전트 등록부</h1>
      <p className="muted">부서 에이전트마다 쓸 수 있는 도구와 위험 등급별 실행 방식, 모델 정책입니다.</p>
      {state.status === 'loading' && <p className="muted">불러오는 중입니다.</p>}
      {state.status === 'error' && <p role="alert">{state.message}</p>}
      {state.status === 'ok' &&
        (state.items.length === 0 ? (
          <p className="muted">등록된 에이전트가 없습니다.</p>
        ) : (
          state.items.map((a) => <AgentCard key={a.id} agent={a} isFallback={a.id === state.fallbackAgentId} />)
        ))}
    </main>
  )
}

const RISKS: { risk: Risk; key: keyof Entry['riskPolicy'] }[] = [
  { risk: 'read', key: 'read' },
  { risk: 'reversible_write', key: 'reversibleWrite' },
  { risk: 'irreversible', key: 'irreversible' },
]

function AgentCard({ agent: a, isFallback }: { agent: Entry; isFallback: boolean }) {
  const titleId = `agent-${a.id}-title`
  return (
    <Card
      id={`agent-${a.id}`}
      aria-labelledby={titleId}
      className="registry__card"
      header={
        <>
          <strong id={titleId}>{a.name}</strong>
          <code className="muted">v{a.version}</code>
          <Badge>{a.stage}단계</Badge>
          {a.modelPolicy.mode === 'local_only' ? <Badge tone="local">로컬 모델만</Badge> : <Badge>외부 모델 허용</Badge>}
          {isFallback && <Badge tone="accent">기본 에이전트</Badge>}
          {a.callable === false && <Badge tone="danger">부를 수 없음</Badge>}
        </>
      }
    >
      <p>{a.description}</p>
      <dl className="registry__meta">
        <div>
          <dt>담당 부서</dt>
          <dd>{a.ownerUnitName ?? a.ownerUnitId}</dd>
        </div>
        <div>
          <dt>부를 수 있는 사람</dt>
          <dd>{callableByText(a.callableBy)}</dd>
        </div>
        <div>
          <dt>문서 범위</dt>
          <dd>{a.docScopes?.length ? a.docScopes.join(', ') : '없음'}</dd>
        </div>
        {a.modelPolicy.reason && (
          <div>
            <dt>모델 정책 이유</dt>
            <dd>{a.modelPolicy.reason}</dd>
          </div>
        )}
      </dl>

      <h3 className="org__h">위험 등급별 실행</h3>
      <table className="table registry__policy">
        <tbody>
          {RISKS.map(({ risk, key }) => {
            const action = a.riskPolicy[key] as Schemas['RiskAction']
            const allowed = a.allowedRisk.includes(risk)
            return (
              <tr key={risk}>
                <th scope="row">
                  <RiskBadge risk={risk} />
                </th>
                <td className={action === 'deny' || !allowed ? 'registry__deny' : undefined}>
                  {allowed ? RISK_ACTION[action] : '허용 안 함'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {a.riskPolicy.overrides?.map((o) => (
        <p key={`${o.tool}-${JSON.stringify(o.when)}`} className="muted">
          예외: <code>{o.tool}</code>은 {overrideWhen(o.when)} {RISK_ACTION[o.action]}
        </p>
      ))}

      <h3 className="org__h">도구 {a.tools.length}개</h3>
      <ul className="registry__tools">
        {a.tools.map((t) => (
          <li key={t.name}>
            <code>{t.name}</code>
            <RiskBadge risk={t.risk} />
          </li>
        ))}
      </ul>
      {a.routingKeywords && a.routingKeywords.length > 0 && (
        <p className="muted">라우팅 낱말: {a.routingKeywords.join(', ')}</p>
      )}
    </Card>
  )
}
