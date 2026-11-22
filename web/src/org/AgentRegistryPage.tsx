import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { api, problemTitle, type Schemas } from '../api/client'
import type { Risk } from '../components/Badge'
import { GroupHead } from '../components/Group'
import { agentLabel, toolName } from '../display/names'
import { Toolbar } from '../shell/Toolbar'
import { callableByText, josa, overrideWhen, RISK_ACTION, RISK_LABEL } from './labels'
import './org.css'

type Entry = Schemas['AgentRegistryEntry']
type State = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ok'; items: Entry[]; fallbackAgentId?: string }

/** AI 에이전트(직원이 "무엇을 시킬 수 있는지" 보는 화면). 에이전트마다 할 수 있는 일과 실행 방식을 묶음 목록으로 보입니다 */
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
            : { status: 'error', message: problemTitle(error, 'AI 에이전트를 불러오지 못했습니다.') },
        ),
      () => alive && setState({ status: 'error', message: '서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.' }),
    )
    return () => {
      alive = false
    }
  }, [])

  // 조직도에서 #agent-<id>로 들어오면 그 에이전트로 옮기고 제목에 포커스를 둡니다.
  useEffect(() => {
    if (state.status !== 'ok' || !hash) return
    const card = document.getElementById(decodeURIComponent(hash.slice(1)))
    card?.scrollIntoView?.({ block: 'start' })
    card?.querySelector<HTMLElement>('h2')?.focus({ preventScroll: true })
  }, [state.status, hash])

  return (
    <main className="registry" aria-labelledby="registry-title">
      <Toolbar title="AI 에이전트" titleId="registry-title" />
      <div className="registry__body">
        <p className="registry__intro">부서마다 담당 AI가 있습니다. AI 비서에 적은 말에 맞는 담당 AI가 답하고, 아래의 일을 대신 합니다.</p>
        {state.status === 'loading' && <p className="org__muted">불러오는 중입니다.</p>}
        {state.status === 'error' && (
          <p role="alert" className="org__error">
            {state.message}
          </p>
        )}
        {state.status === 'ok' &&
          (state.items.length === 0 ? (
            <p className="org__muted">등록된 AI 에이전트가 없습니다.</p>
          ) : (
            state.items.map((a) => <AgentSection key={a.id} agent={a} isFallback={a.id === state.fallbackAgentId} />)
          ))}
      </div>
    </main>
  )
}

const POLICY_KEY: Record<Risk, keyof Entry['riskPolicy']> = { read: 'read', reversible_write: 'reversibleWrite', irreversible: 'irreversible' }

/** 일 하나를 어떻게 하는지: 허용하지 않는 등급이면 "하지 않음", 아니면 등급별 정책 */
function actionOf(a: Entry, risk: Risk): { label: string; denied: boolean } {
  const action = a.riskPolicy[POLICY_KEY[risk]] as Schemas['RiskAction']
  const denied = !a.allowedRisk.includes(risk) || action === 'deny'
  return { label: denied ? RISK_ACTION.deny : RISK_ACTION[action], denied }
}

function AgentSection({ agent: a, isFallback }: { agent: Entry; isFallback: boolean }) {
  const titleId = `agent-${a.id}-title`
  const name = agentLabel(a.name)
  const local = a.modelPolicy.mode === 'local_only'
  return (
    <section id={`agent-${a.id}`} className="agent" aria-labelledby={titleId}>
      <header className="agent__head">
        <h2 id={titleId} className="agent__name" tabIndex={-1}>
          {name}
        </h2>
        {a.callable === false && <span className="tag">사용할 수 없음</span>}
        <span className="agent__ver">
          v{a.version} · {a.stage}단계
        </span>
      </header>
      <p className="agent__desc">{a.description}</p>
      {isFallback && <p className="agent__note">맞는 담당 AI가 없으면 {name}{josa(name, '이', '가')} 답합니다.</p>}

      <dl className="rows agent__meta">
        <div className="row">
          <dt className="row__label">담당 부서</dt>
          <dd>{a.ownerUnitName ?? a.ownerUnitId}</dd>
        </div>
        <div className="row">
          <dt className="row__label">사용할 수 있는 사람</dt>
          <dd>{callableByText(a.callableBy)}</dd>
        </div>
        <div className="row">
          <dt className="row__label">AI 처리</dt>
          <dd>
            {local ? '사내 처리' : '외부 AI 사용'}
            {a.modelPolicy.reason && <span className="agent__reason">{a.modelPolicy.reason}</span>}
          </dd>
        </div>
        {a.routingKeywords && a.routingKeywords.length > 0 && (
          <div className="row">
            <dt className="row__label">맡는 말</dt>
            <dd>{a.routingKeywords.join(', ')}</dd>
          </div>
        )}
      </dl>

      <section className="group" aria-labelledby={`agent-${a.id}-tools`}>
        <GroupHead id={`agent-${a.id}-tools`} title="할 수 있는 일" n={a.tools.length ? `${a.tools.length}가지` : undefined} />
        {a.tools.length === 0 && <p className="group__empty">할 수 있는 일이 없습니다.</p>}
        <ul className="group__list" hidden={a.tools.length === 0}>
          {a.tools.map((t) => {
            const how = actionOf(a, t.risk)
            const overrides = how.denied ? [] : (a.riskPolicy.overrides ?? []).filter((o) => o.tool === t.name)
            return (
              <li key={t.name}>
                <div className="group__row">
                  <span className="group__main">
                    <span className="group__title">{toolName(t.name)}</span>
                    <span className="group__sub">
                      {RISK_LABEL[t.risk]} · <code className="agent__code">{t.name}</code>
                    </span>
                    {overrides.map((o, i) => (
                      <span key={i} className="group__sub">
                        {overrideWhen(o)} {RISK_ACTION[o.action]}
                      </span>
                    ))}
                  </span>
                  <span className={how.denied ? 'group__end agent__deny' : 'group__end'}>{how.label}</span>
                </div>
              </li>
            )
          })}
        </ul>
      </section>
    </section>
  )
}
