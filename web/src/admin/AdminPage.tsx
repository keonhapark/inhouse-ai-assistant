import { useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Button } from '../components/Button'
import { AuditPanel } from './AuditPanel'
import { EgressPanel } from './EgressPanel'
import { MetricsPanel } from './MetricsPanel'
import { PRESETS, toRange, ymd, type Period } from './period'
import '../inbox/inbox.css'
import './admin.css'
import { formatDateRange } from '../display/format'

const TABS = [
  { id: 'metrics', label: '운영 지표' },
  { id: 'egress', label: '외부 전송 기록' },
  { id: 'audit', label: '감사 로그' },
] as const
type Tab = (typeof TABS)[number]['id']

export type Range = { since: string; until: string }

export function AdminPage() {
  const [tab, setTab] = useState<Tab>('metrics')
  const [period, setPeriod] = useState<Period>({ kind: 'preset', preset: '24h' })
  // 기간은 적용할 때 한 번 시각으로 바꿔 둡니다. 다시 그릴 때마다 '지금'이 바뀌어 다시 불러오지 않게 합니다.
  const [range, setRange] = useState<Range>(() => toRange({ kind: 'preset', preset: '24h' })!)
  // 날짜 입력의 처음 값(지난 7일)과 고를 수 있는 마지막 날(오늘)은 화면을 열 때 한 번만 정합니다.
  const [today] = useState(() => ymd(new Date()))
  const [from, setFrom] = useState(() => ymd(new Date(Date.now() - 6 * 86_400_000)))
  const [to, setTo] = useState(today)
  const [rangeError, setRangeError] = useState<string | null>(null)
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([])

  function applyPreset(p: Period) {
    setPeriod(p)
    setRangeError(null)
    setRange(toRange(p)!)
  }

  function applyCustom(e: FormEvent) {
    e.preventDefault()
    const p: Period = { kind: 'custom', from, to }
    const r = toRange(p)
    if (!r) return setRangeError('시작 날짜가 끝 날짜보다 늦거나 비었습니다.')
    setPeriod(p)
    setRangeError(null)
    setRange(r)
  }

  function onTabKey(e: KeyboardEvent, i: number) {
    const last = TABS.length - 1
    const next = e.key === 'ArrowRight' ? (i === last ? 0 : i + 1) : e.key === 'ArrowLeft' ? (i === 0 ? last : i - 1) : e.key === 'Home' ? 0 : e.key === 'End' ? last : -1
    if (next < 0) return
    e.preventDefault()
    tabRefs.current[next]?.focus()
    setTab(TABS[next].id)
  }

  return (
    <main className="admin">
      <h1>관리자 콘솔</h1>
      <div className="admin__filters" role="group" aria-label="기간">
        {PRESETS.map((p) => (
          <Button
            key={p.preset}
            aria-pressed={period.kind === 'preset' && period.preset === p.preset}
            variant={period.kind === 'preset' && period.preset === p.preset ? 'primary' : 'secondary'}
            onClick={() => applyPreset({ kind: 'preset', preset: p.preset })}
          >
            최근 {p.label}
          </Button>
        ))}
        <form className="admin__custom" onSubmit={applyCustom}>
          <label>
            <span className="muted">시작</span>
            <input type="date" value={from} max={today} aria-invalid={!!rangeError} aria-describedby={rangeError ? 'admin-range-error' : undefined} onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label>
            <span className="muted">끝</span>
            <input type="date" value={to} max={today} aria-invalid={!!rangeError} aria-describedby={rangeError ? 'admin-range-error' : undefined} onChange={(e) => setTo(e.target.value)} />
          </label>
          <Button type="submit" variant={period.kind === 'custom' ? 'primary' : 'secondary'}>
            날짜로 보기
          </Button>
        </form>
      </div>
      {rangeError && (
        <p role="alert" id="admin-range-error">
          {rangeError}
        </p>
      )}
      <p className="muted admin__period" aria-live="polite">
        {period.kind === 'custom' ? formatDateRange(period.from, period.to) : `최근 ${PRESETS.find((p) => p.preset === period.preset)?.label}`}을 보고 있습니다.
      </p>

      <div role="tablist" aria-label="관리자 콘솔" className="tabs">
        {TABS.map((t, i) => (
          <button
            key={t.id}
            ref={(el) => {
              tabRefs.current[i] = el
            }}
            role="tab"
            id={`admin-tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls="admin-panel"
            tabIndex={tab === t.id ? 0 : -1}
            className="tabs__tab"
            onClick={() => setTab(t.id)}
            onKeyDown={(e) => onTabKey(e, i)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="admin-panel" aria-labelledby={`admin-tab-${tab}`} className="admin__panel" tabIndex={0}>
        {tab === 'metrics' && <MetricsPanel range={range} />}
        {tab === 'egress' && <EgressPanel range={range} />}
        {tab === 'audit' && <AuditPanel range={range} />}
      </div>
    </main>
  )
}
