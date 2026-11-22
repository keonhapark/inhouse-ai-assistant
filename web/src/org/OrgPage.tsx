import { Bot, ChevronRight, Search } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { api, problemTitle, type Schemas } from '../api/client'
import { GroupHead } from '../components/Group'
import { agentLabel } from '../display/names'
import { Toolbar } from '../shell/Toolbar'
import { gradeName, josa, UNIT_KIND } from './labels'
import { buildTree, pathTo, type Unit, type UnitNode } from './tree'
import './org.css'

type Load<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ok'; data: T }
type Person = Schemas['EmployeeSummary']
const NETWORK = '서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.'
/** 한 번에 불러오는 구성원 수(계약 /employees limit 최댓값). 이만큼 오면 잘렸다고 알립니다. */
export const MEMBER_LIMIT = 100
/** 사람 찾기 결과 수 */
export const SEARCH_LIMIT = 20
/** 글자를 다 친 뒤 찾기까지 기다리는 시간(ms) */
const SEARCH_WAIT = 250
const NARROW = '(max-width: 720px)'

/** 명령 팔레트의 "사람 찾기"가 조직도로 옮기며 넘기는 상태. 찾기 칸에 초점을 둡니다 */
export type OrgNavState = { find?: boolean }

export function OrgPage() {
  const [units, setUnits] = useState<Load<Unit[]>>({ status: 'loading' })
  const [agents, setAgents] = useState<Load<Schemas['AgentRegistryEntry'][]>>({ status: 'loading' })
  // 구성원은 어느 부서의 것인지 함께 둡니다. 부서가 바뀌었는데 아직 앞 부서 것이면 불러오는 중으로 봅니다.
  const [members, setMembers] = useState<{ unitId: string; load: Load<Person[]> } | null>(null)
  // 고른 부서(?unit=)와 찾기로 고른 사람(?person=)은 주소에 둡니다. 뒤로 가기와 링크 공유에서 같은 화면이 열립니다.
  const [params, setParams] = useSearchParams()
  const selected = params.get('unit')
  const person = params.get('person')
  const [query, setQuery] = useState('')
  // 찾은 사람도 어느 낱말의 결과인지 함께 둡니다. 낱말이 바뀌었는데 아직 앞 결과면 찾는 중으로 봅니다.
  const [found, setFound] = useState<{ term: string; load: Load<Person[]> } | null>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const focusTitle = useRef<'always' | 'narrow' | null>(null)
  const location = useLocation()

  const all = useMemo(() => (units.status === 'ok' ? units.data : []), [units])
  const tree = useMemo(() => buildTree(all), [all])
  // 주소의 부서가 없거나 목록에 없으면 맨 위 부서를 엽니다.
  const unit = all.find((u) => u.id === selected) ?? all.find((u) => !u.parentId) ?? all[0]
  const unitId = unit?.id
  const people: Load<Person[]> = members && members.unitId === unitId ? members.load : { status: 'loading' }
  const term = query.trim()
  const results: Load<Person[]> | null = term ? (found && found.term === term ? found.load : { status: 'loading' }) : null

  useEffect(() => {
    let alive = true
    api.GET('/org/units').then(
      ({ data, error }) =>
        alive && setUnits(data ? { status: 'ok', data: data.items } : { status: 'error', message: problemTitle(error, '조직도를 불러오지 못했습니다.') }),
      () => alive && setUnits({ status: 'error', message: NETWORK }),
    )
    api.GET('/agent-registry').then(
      ({ data, error }) =>
        alive && setAgents(data ? { status: 'ok', data: data.items } : { status: 'error', message: problemTitle(error, 'AI 에이전트를 불러오지 못했습니다.') }),
      () => alive && setAgents({ status: 'error', message: 'AI 에이전트를 불러오지 못했습니다.' }),
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

  // 사람 찾기: 글자를 멈추고 잠시 뒤 이름 일부로 찾습니다. 낱말이 다시 바뀌면 앞 요청의 응답은 버립니다.
  useEffect(() => {
    if (!term) return
    let current = true
    const timer = setTimeout(() => {
      api.GET('/employees', { params: { query: { q: term, limit: SEARCH_LIMIT } } }).then(
        ({ data, error }) =>
          current &&
          setFound({ term, load: data ? { status: 'ok', data: data.items } : { status: 'error', message: problemTitle(error, '사람을 찾지 못했습니다.') } }),
        () => current && setFound({ term, load: { status: 'error', message: NETWORK } }),
      )
    }, SEARCH_WAIT)
    return () => {
      current = false
      clearTimeout(timer)
    }
  }, [term])

  // 명령 팔레트의 "사람 찾기"로 들어오면 찾기 칸에 초점을 둡니다(이미 조직도에 있어도 매번).
  useEffect(() => {
    if ((location.state as OrgNavState | null)?.find) searchRef.current?.focus()
  }, [location.key, location.state])

  // 상세 안의 버튼이나 찾은 사람으로 고르면 제목으로 포커스를 옮깁니다. 좁은 화면에서는 왼쪽 열 아래 상세가 보이게 합니다.
  useEffect(() => {
    const how = focusTitle.current
    focusTitle.current = null
    if (!how || !titleRef.current) return
    const narrow = globalThis.matchMedia?.(NARROW).matches ?? false
    if (how === 'always' || narrow) {
      titleRef.current.focus({ preventScroll: !narrow })
      if (narrow) titleRef.current.scrollIntoView?.({ block: 'start' })
    }
  }, [unitId, person])

  function select(id: string, from: 'tree' | 'detail') {
    if (id === unitId && !person) return
    focusTitle.current = from === 'detail' ? 'always' : 'narrow'
    setParams({ unit: id })
  }

  function pick(p: Person) {
    if (p.unitId === unitId && p.id === person) return
    focusTitle.current = 'always'
    setParams({ unit: p.unitId, person: p.id })
  }

  function onSearchKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Escape' && query) {
      e.preventDefault()
      setQuery('')
    }
  }

  return (
    <main className="org" aria-labelledby="org-title">
      <Toolbar title="조직도" titleId="org-title" />
      <div className="org__body">
        <div className="org__side">
          <div role="search" className="org__search">
            <label htmlFor="org-find" className="visually-hidden">
              사람 찾기
            </label>
            <Search aria-hidden />
            <input
              ref={searchRef}
              id="org-find"
              type="search"
              autoComplete="off"
              placeholder="이름으로 사람 찾기"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onSearchKey}
            />
          </div>
          {results ? (
            <Found results={results} term={term} selected={person} onPick={pick} />
          ) : (
            <nav className="org__tree" aria-label="부서">
              {units.status === 'loading' && <p className="org__muted">불러오는 중입니다.</p>}
              {units.status === 'error' && (
                <p role="alert" className="org__error">
                  {units.message}
                </p>
              )}
              {units.status === 'ok' &&
                (tree.length === 0 ? (
                  <p className="org__muted">등록된 부서가 없습니다.</p>
                ) : (
                  <TreeList nodes={tree} selected={unitId} onSelect={(id) => select(id, 'tree')} />
                ))}
            </nav>
          )}
        </div>
        <div className="org__main">
          {unit && (
            <UnitDetail
              unit={unit}
              titleRef={titleRef}
              path={pathTo(all, unit.id)}
              subUnits={all.filter((u) => u.parentId === unit.id)}
              people={people}
              person={person}
              agents={agents}
              onSelect={(id) => select(id, 'detail')}
            />
          )}
        </div>
      </div>
    </main>
  )
}

/** 사람 찾기 결과. 고르면 그 사람의 부서를 열고 행을 표시합니다 */
function Found({ results, term, selected, onPick }: { results: Load<Person[]>; term: string; selected: string | null; onPick: (p: Person) => void }) {
  return (
    <section className="group" aria-labelledby="org-found">
      <GroupHead id="org-found" level={2} title="찾은 사람" n={results.status === 'ok' ? `${results.data.length}명` : undefined} />
      {results.status === 'loading' && <p className="group__empty">찾는 중입니다.</p>}
      {results.status === 'error' && (
        <p role="alert" className="group__empty org__error">
          {results.message}
        </p>
      )}
      {results.status === 'ok' &&
        (results.data.length === 0 ? (
          <p role="status" className="group__empty">
            이름에 “{term}”{josa(term, '이', '가')} 들어간 사람이 없습니다.
          </p>
        ) : (
          <>
            <ul className="group__list">
              {results.data.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    className="group__row"
                    aria-current={p.id === selected ? 'true' : undefined}
                    aria-labelledby={`found-n-${p.id}`}
                    aria-describedby={`found-${p.id}`}
                    onClick={() => onPick(p)}
                  >
                    <span className="avatar" aria-hidden>
                      {p.name.slice(0, 1)}
                    </span>
                    <span className="group__main">
                      <span id={`found-n-${p.id}`} className="group__title">
                        {p.name}
                      </span>
                      <span id={`found-${p.id}`} className="group__sub">
                        {gradeName(p.grade)} · {p.unitName}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            {results.data.length >= SEARCH_LIMIT && <p className="org__muted">앞 {SEARCH_LIMIT}명만 보여 줍니다. 이름을 더 적어 보세요.</p>}
          </>
        ))}
    </section>
  )
}

function TreeList({ nodes, selected, onSelect }: { nodes: UnitNode[]; selected?: string; onSelect: (id: string) => void }) {
  return (
    <ul className="org__list">
      {nodes.map((n) => (
        <li key={n.id}>
          <button type="button" className="org__node" aria-current={n.id === selected ? 'true' : undefined} onClick={() => onSelect(n.id)}>
            {n.name}
            {n.kind === 'division' && <span className="org__kind"> {UNIT_KIND.division}</span>}
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
  people: Load<Person[]>
  person: string | null
  agents: Load<Schemas['AgentRegistryEntry'][]>
  onSelect: (id: string) => void
}

function UnitDetail({ unit, titleRef, path, subUnits, people, person, agents, onSelect }: DetailProps) {
  const owned = agents.status === 'ok' ? agents.data.filter((a) => a.ownerUnitId === unit.id) : []
  return (
    <section className="org__detail" aria-label={`${unit.name} 상세`}>
      <header className="org__head">
        {path.length > 1 && (
          <ol className="org__path" aria-label="상위 부서">
            {path.slice(0, -1).map((p) => (
              <li key={p.id}>
                <button type="button" className="btn btn--link" onClick={() => onSelect(p.id)}>
                  {p.name}
                </button>
              </li>
            ))}
          </ol>
        )}
        <h2 className="org__name" ref={titleRef} tabIndex={-1}>
          {unit.name} <span className="tag">{UNIT_KIND[unit.kind]}</span>
        </h2>
      </header>

      <section className="group" aria-labelledby="org-members">
        <GroupHead id="org-members" title="구성원" n={people.status === 'ok' && people.data.length > 0 ? `${people.data.length}명` : undefined} />
        {people.status === 'loading' && <p className="group__empty">불러오는 중입니다.</p>}
        {people.status === 'error' && (
          <p role="alert" className="group__empty org__error">
            {people.message}
          </p>
        )}
        {people.status === 'ok' &&
          (people.data.length === 0 ? (
            <p className="group__empty">이 부서에 바로 속한 구성원이 없습니다. 하위 부서를 골라 보세요.</p>
          ) : (
            <>
              <ul className="group__list">
                {[...people.data]
                  .sort((a, b) => Number(b.id === unit.headId) - Number(a.id === unit.headId))
                  .map((p) => (
                    <li key={p.id}>
                      <div className="group__row" aria-current={p.id === person ? 'true' : undefined}>
                        <span className="avatar" aria-hidden>
                          {p.name.slice(0, 1)}
                        </span>
                        <span className="group__main">
                          <span className="group__title">
                            {p.name}
                            {p.id === unit.headId && <span className="tag org__head-tag">부서장</span>}
                          </span>
                        </span>
                        <span className="group__end">{gradeName(p.grade)}</span>
                      </div>
                    </li>
                  ))}
              </ul>
              {people.data.length >= MEMBER_LIMIT && <p className="org__muted">앞 {MEMBER_LIMIT}명만 보여 줍니다.</p>}
            </>
          ))}
      </section>

      {subUnits.length > 0 && (
        <section className="group" aria-labelledby="org-subunits">
          <GroupHead id="org-subunits" title="하위 부서" n={`${subUnits.length}곳`} />
          <ul className="group__list">
            {subUnits.map((s) => (
              <li key={s.id}>
                <button type="button" className="group__row" onClick={() => onSelect(s.id)}>
                  <span className="group__main group__title">{s.name}</span>
                  <ChevronRight aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="group" aria-labelledby="org-agents">
        <GroupHead id="org-agents" title="담당 AI 에이전트" />
        {agents.status === 'loading' && <p className="group__empty">불러오는 중입니다.</p>}
        {agents.status === 'error' && <p className="group__empty">{agents.message}</p>}
        {agents.status === 'ok' &&
          (owned.length === 0 ? (
            <p className="group__empty">이 부서가 맡은 AI 에이전트가 없습니다.</p>
          ) : (
            <ul className="group__list">
              {owned.map((a) => (
                <li key={a.id}>
                  <Link className="group__row" to={`/agents#agent-${a.id}`}>
                    <Bot aria-hidden className="org__bot" />
                    <span className="group__main group__title">{agentLabel(a.name)}</span>
                    <ChevronRight aria-hidden />
                  </Link>
                </li>
              ))}
            </ul>
          ))}
      </section>
    </section>
  )
}
