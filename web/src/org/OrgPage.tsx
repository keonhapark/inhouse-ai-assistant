import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, problemTitle, type Schemas } from '../api/client'
import { Badge } from '../components/Badge'
import { gradeName, UNIT_KIND } from './labels'
import { buildTree, pathTo, type Unit, type UnitNode } from './tree'
import '../inbox/inbox.css'
import './org.css'

type Load<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ok'; data: T }
const NETWORK = '서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.'
/** 한 번에 불러오는 구성원 수(계약 /employees limit 최댓값). 이만큼 오면 잘렸다고 알립니다. */
export const MEMBER_LIMIT = 100
const NARROW = '(max-width: 720px)'

export function OrgPage() {
  const [units, setUnits] = useState<Load<Unit[]>>({ status: 'loading' })
  const [agents, setAgents] = useState<Load<Schemas['AgentRegistryEntry'][]>>({ status: 'loading' })
  // 구성원은 어느 부서의 것인지 함께 둡니다. 부서가 바뀌었는데 아직 앞 부서 것이면 불러오는 중으로 봅니다.
  const [members, setMembers] = useState<{ unitId: string; load: Load<Schemas['EmployeeSummary'][]> } | null>(null)
  // 고른 부서는 주소(?unit=)에 둡니다. 뒤로 가기와 링크 공유에서 같은 부서가 열립니다.
  const [params, setParams] = useSearchParams()
  const selected = params.get('unit')
  const titleRef = useRef<HTMLHeadingElement>(null)
  const focusTitle = useRef<'always' | 'narrow' | null>(null)

  const all = useMemo(() => (units.status === 'ok' ? units.data : []), [units])
  const tree = useMemo(() => buildTree(all), [all])
  // 주소의 부서가 없거나 목록에 없으면 맨 위 부서를 엽니다.
  const unit = all.find((u) => u.id === selected) ?? all.find((u) => !u.parentId) ?? all[0]
  const unitId = unit?.id
  const people: Load<Schemas['EmployeeSummary'][]> = members && members.unitId === unitId ? members.load : { status: 'loading' }

  useEffect(() => {
    let alive = true
    api.GET('/org/units').then(
      ({ data, error }) =>
        alive && setUnits(data ? { status: 'ok', data: data.items } : { status: 'error', message: problemTitle(error, '조직도를 불러오지 못했습니다.') }),
      () => alive && setUnits({ status: 'error', message: NETWORK }),
    )
    api.GET('/agent-registry').then(
      ({ data, error }) =>
        alive && setAgents(data ? { status: 'ok', data: data.items } : { status: 'error', message: problemTitle(error, '에이전트 등록부를 불러오지 못했습니다.') }),
      () => alive && setAgents({ status: 'error', message: '에이전트 등록부를 불러오지 못했습니다.' }),
    )
    return () => {
      alive = false
    }
  }, [])

  // 부서가 바뀌면 구성원을 불러옵니다. 부서가 다시 바뀌었거나 화면을 떠난 뒤 온 응답은 버립니다.
  useEffect(() => {
    if (!unitId) return
    let current = true
    api.GET('/employees', { params: { query: { unitId, limit: MEMBER_LIMIT } } }).then(
      ({ data, error }) =>
        current &&
        setMembers({ unitId, load: data ? { status: 'ok', data: data.items } : { status: 'error', message: problemTitle(error, '구성원을 불러오지 못했습니다.') } }),
      () => current && setMembers({ unitId, load: { status: 'error', message: NETWORK } }),
    )
    return () => {
      current = false
    }
  }, [unitId])

  // 상세 안의 버튼으로 고르면 누른 버튼이 사라지므로 제목으로 포커스를 옮깁니다. 좁은 화면에서는 나무 아래 상세가 보이게 합니다.
  useEffect(() => {
    const how = focusTitle.current
    focusTitle.current = null
    if (!how || !titleRef.current) return
    const narrow = globalThis.matchMedia?.(NARROW).matches ?? false
    if (how === 'always' || narrow) {
      titleRef.current.focus({ preventScroll: !narrow })
      if (narrow) titleRef.current.scrollIntoView?.({ block: 'start' })
    }
  }, [unitId])

  function select(id: string, from: 'tree' | 'detail') {
    if (id === unitId) return
    focusTitle.current = from === 'detail' ? 'always' : 'narrow'
    setParams({ unit: id })
  }

  return (
    <main className="org">
      <h1 className="org__title">조직도</h1>
      <div className="org__body">
        <nav className="org__tree" aria-label="부서">
          {units.status === 'loading' && <p className="muted">불러오는 중입니다.</p>}
          {units.status === 'error' && <p role="alert">{units.message}</p>}
          {units.status === 'ok' &&
            (tree.length === 0 ? (
              <p className="muted">등록된 부서가 없습니다.</p>
            ) : (
              <TreeList nodes={tree} selected={unitId} onSelect={(id) => select(id, 'tree')} />
            ))}
        </nav>
        <div className="org__main">
          {unit && (
            <UnitDetail
              unit={unit}
              titleRef={titleRef}
              path={pathTo(all, unit.id)}
              subUnits={all.filter((u) => u.parentId === unit.id)}
              people={people}
              agents={agents}
              onSelect={(id) => select(id, 'detail')}
            />
          )}
        </div>
      </div>
    </main>
  )
}

function TreeList({ nodes, selected, onSelect }: { nodes: UnitNode[]; selected?: string; onSelect: (id: string) => void }) {
  return (
    <ul className="org__list">
      {nodes.map((n) => (
        <li key={n.id}>
          <button
            type="button"
            className="org__node"
            aria-current={n.id === selected ? 'true' : undefined}
            onClick={() => onSelect(n.id)}
          >
            {n.name}
            {n.kind === 'division' && <span className="muted"> {UNIT_KIND.division}</span>}
          </button>
          {n.children.length > 0 && <TreeList nodes={n.children} selected={selected} onSelect={onSelect} />}
        </li>
      ))}
    </ul>
  )
}

type DetailProps = {
  unit: Unit
  titleRef: React.RefObject<HTMLHeadingElement | null>
  path: Unit[]
  subUnits: Unit[]
  people: Load<Schemas['EmployeeSummary'][]>
  agents: Load<Schemas['AgentRegistryEntry'][]>
  onSelect: (id: string) => void
}

function UnitDetail({ unit, titleRef, path, subUnits, people, agents, onSelect }: DetailProps) {
  const owned = agents.status === 'ok' ? agents.data.filter((a) => a.ownerUnitId === unit.id) : []
  return (
    <section className="org__detail" aria-label={`${unit.name} 상세`}>
      {path.length > 1 && (
        <ol className="org__path" aria-label="상위 부서">
          {path.slice(0, -1).map((p) => (
            <li key={p.id}>
              <button type="button" className="link" onClick={() => onSelect(p.id)}>
                {p.name}
              </button>
            </li>
          ))}
        </ol>
      )}
      <h2 className="org__name" ref={titleRef} tabIndex={-1}>
        {unit.name} <Badge>{UNIT_KIND[unit.kind]}</Badge>
      </h2>

      <h3 className="org__h">구성원</h3>
      {people.status === 'loading' && <p className="muted">불러오는 중입니다.</p>}
      {people.status === 'error' && <p role="alert">{people.message}</p>}
      {people.status === 'ok' &&
        (people.data.length === 0 ? (
          <p className="muted">이 부서에 바로 속한 구성원이 없습니다. 하위 부서를 골라 보세요.</p>
        ) : (
          <>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">이름</th>
                  <th scope="col">직급</th>
                </tr>
              </thead>
              <tbody>
                {[...people.data]
                  .sort((a, b) => Number(b.id === unit.headId) - Number(a.id === unit.headId))
                  .map((p) => (
                    <tr key={p.id}>
                      <td>
                        {p.name}
                        {p.id === unit.headId && <Badge tone="accent">부서장</Badge>}
                      </td>
                      <td>{gradeName(p.grade)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
            {people.data.length >= MEMBER_LIMIT && <p className="muted">앞 {MEMBER_LIMIT}명만 보여 줍니다.</p>}
          </>
        ))}

      {subUnits.length > 0 && (
        <>
          <h3 className="org__h">하위 부서</h3>
          <ul className="org__chips">
            {subUnits.map((s) => (
              <li key={s.id}>
                <button type="button" className="link" onClick={() => onSelect(s.id)}>
                  {s.name}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      <h3 className="org__h">담당 에이전트</h3>
      {agents.status === 'loading' && <p className="muted">불러오는 중입니다.</p>}
      {agents.status === 'error' && <p className="muted">{agents.message}</p>}
      {agents.status === 'ok' &&
        (owned.length === 0 ? (
          <p className="muted">이 부서가 맡은 에이전트가 없습니다.</p>
        ) : (
          <ul className="org__chips">
            {owned.map((a) => (
              <li key={a.id}>
                <Link to={`/agents#agent-${a.id}`}>{a.name}</Link>
              </li>
            ))}
          </ul>
        ))}
    </section>
  )
}
