import { useEffect, useId, useState } from 'react'
import { api, problemTitle, type Schemas } from '../api/client'

type EmployeeSummary = Schemas['EmployeeSummary']

/** 대리인 고르기. 이름 일부로 찾고(GET /employees) 결과에서 한 명을 고릅니다. */
export function DelegatePicker({ value, excludeId, onChange }: { value: string; excludeId?: string | null; onChange(id: string): void }) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<EmployeeSummary[]>([])
  const [picked, setPicked] = useState<EmployeeSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const groupId = useId()

  useEffect(() => {
    const term = q.trim()
    if (!term) return
    let alive = true
    // 글자를 칠 때마다 부르지 않도록 잠깐 기다립니다.
    const t = setTimeout(() => {
      api.GET('/employees', { params: { query: { q: term, limit: 10 } } }).then(
        ({ data, error: p }) => {
          if (!alive) return
          setResults((data?.items ?? []).filter((e) => e.id !== excludeId))
          setError(data ? null : problemTitle(p, '직원을 찾지 못했습니다.'))
        },
        () => alive && setError('서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.'),
      )
    }, 250)
    return () => {
      alive = false
      clearTimeout(t)
    }
  }, [q, excludeId])

  const shown = q.trim() ? results : []

  return (
    <fieldset className="picker">
      <legend>대결자</legend>
      {value && picked?.id === value ? (
        <p>
          <strong>{picked.name}</strong> <span className="muted">{picked.unitName}</span>
        </p>
      ) : (
        <p className="muted">아직 고르지 않았습니다.</p>
      )}
      <label>
        이름 검색
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} />
      </label>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {shown.length > 0 && (
        <div role="radiogroup" aria-label="찾은 직원" className="picker__results">
          {shown.map((e) => (
            <label key={e.id} className="picker__option">
              <input
                type="radio"
                name={groupId}
                checked={value === e.id}
                onChange={() => {
                  setPicked(e)
                  onChange(e.id)
                }}
              />
              {e.name} <span className="muted">{e.unitName}</span>
            </label>
          ))}
        </div>
      )}
      {q.trim() && shown.length === 0 && !error && <p className="muted">찾은 직원이 없습니다.</p>}
    </fieldset>
  )
}
