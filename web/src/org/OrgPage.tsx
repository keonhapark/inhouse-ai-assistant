import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, problemTitle, type Schemas } from '../api/client'
import { Badge } from '../components/Badge'
import { gradeName, UNIT_KIND } from './labels'
import { buildTree, pathTo, type Unit, type UnitNode } from './tree'
import '../inbox/inbox.css'
import './org.css'

type Load<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ok'; data: T }
const NETWORK = '서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.'

export function OrgPage() {
  const [units, setUnits] = useState<Load<Unit[]>>({ status: 'loading' })
  const [agents, setAgents] = useState<Schemas['AgentRegistryEntry'][]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [people, setPeople] = useState<Load<Schemas['EmployeeSummary'][]>>({ status: 'loading' })
  const request = useRef(0)

  /** 부서를 고르고 구성원을 불러옵니다. 늦게 온 앞 요청의 응답은 버립니다. */
  function select(unitId: string) {
    const id = ++request.current
    setSelected(unitId)
    setPeople({ status: 'loading' })
    api.GET('/employees', { params: { query: { unitId, limit: 100 } } }).then(
      ({ data, error }) => {
        if (id !== request.current) return
        setPeople(data ? { status: 'ok', data: data.items } : { status: 'error', message: problemTitle(error, '구성원을 불러오지 못했습니다.') })
      },
      () => id === request.current && setPeople({ status: 'error', message: NETWORK }),
    )
  }

  useEffect(() => {
    let alive = true
    api.GET('/org/units').then(
      ({ data, error }) => {
        if (!alive) return
        if (!data) return setUnits({ status: 'error', message: problemTitle(error, '조직도를 불러오지 못했습니다.') })
        setUnits({ status: 'ok', data: data.items })
        const first = data.items.find((u) => !u.parentId) ?? data.items[0]
        if (first) select(first.id)
      },
      () => alive && setUnits({ status: 'error', message: NETWORK }),
    )
    // 등록부는 부서에 딸린 에이전트를 보여 주는 데만 씁니다. 실패해도 조직도는 보여 줍니다.
    api.GET('/agent-registry').then(
      ({ data }) => alive && data && setAgents(data.items),
      () => undefined,
    )
    return () => {
      alive = false
    }
    // select는 ref와 setState만 써서 처음 한 번만 부릅니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const all = useMemo(() => (units.status === 'ok' ? units.data : []), [units])
  const tree = useMemo(() => buildTree(all), [all])
  const unit = all.find((u) => u.id === selected)

  return (
    <div className="org">
      <nav className="org__tree" aria-label="부서">
        <h1 className="org__title">조직도</h1>
        {units.status === 'loading' && <p className="muted">불러오는 중입니다.</p>}
        {units.status === 'error' && <p role="alert">{units.message}</p>}
        {units.status === 'ok' && <TreeList nodes={tree} selected={selected} onSelect={select} />}
      </nav>
      <main className="org__main">
        {unit && (
          <UnitDetail
            unit={unit}
            path={pathTo(all, unit.id)}
            subUnits={all.filter((u) => u.parentId === unit.id)}
            people={people}
            agents={agents.filter((a) => a.ownerUnitId === unit.id)}
            onSelect={select}
          />
        )}
      </main>
    </div>
  )
}

function TreeList({ nodes, selected, onSelect }: { nodes: UnitNode[]; selected: string | null; onSelect: (id: string) => void }) {
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
  path: Unit[]
  subUnits: Unit[]
  people: Load<Schemas['EmployeeSummary'][]>
  agents: Schemas['AgentRegistryEntry'][]
  onSelect: (id: string) => void
}

function UnitDetail({ unit, path, subUnits, people, agents, onSelect }: DetailProps) {
  return (
    <section className="org__detail" aria-label={`${unit.name} 상세`}>
      <ol className="org__path" aria-label="상위 부서">
        {path.slice(0, -1).map((p) => (
          <li key={p.id}>
            <button type="button" className="link" onClick={() => onSelect(p.id)}>
              {p.name}
            </button>
          </li>
        ))}
      </ol>
      <h2 className="org__name">
        {unit.name} <Badge>{UNIT_KIND[unit.kind]}</Badge>
      </h2>

      <h3 className="org__h">구성원</h3>
      {people.status === 'loading' && <p className="muted">불러오는 중입니다.</p>}
      {people.status === 'error' && <p role="alert">{people.message}</p>}
      {people.status === 'ok' &&
        (people.data.length === 0 ? (
          <p className="muted">이 부서에 바로 속한 구성원이 없습니다. 하위 부서를 골라 보세요.</p>
        ) : (
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
      {agents.length === 0 ? (
        <p className="muted">이 부서가 맡은 에이전트가 없습니다.</p>
      ) : (
        <ul className="org__chips">
          {agents.map((a) => (
            <li key={a.id}>
              <Link to={`/agents#agent-${a.id}`}>{a.name}</Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
