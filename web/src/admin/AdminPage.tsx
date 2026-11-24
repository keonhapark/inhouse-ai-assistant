import { useState, type FormEvent } from 'react'
import { Navigate, useParams } from 'react-router-dom'
import { Button } from '../components/Button'
import { DateField } from '../components/DatePicker'
import { Toolbar } from '../shell/Toolbar'
import { AuditPanel } from './AuditPanel'
import { EgressPanel } from './EgressPanel'
import { MetricsPanel } from './MetricsPanel'
import { PRESETS, toRange, ymd, type Period } from './period'
import './admin.css'
import { formatDateRange } from '../display/format'

const TABS = [
  { id: 'metrics', label: '운영 지표' },
  { id: 'egress', label: '외부 전송 기록' },
  { id: 'audit', label: '감사 로그' },
] as const
type Tab = (typeof TABS)[number]['id']

export type Range = { since: string; until: string }

const isTab = (v: string | undefined): v is Tab => TABS.some((t) => t.id === v)

/**
 * 운영 화면(/ops/metrics, /ops/egress, /ops/audit). 화면 사이는 왼쪽 탐색 막대의 운영 묶음으로 옮깁니다(ia.md 2절).
 * 세 화면이 같은 경로(/ops/:tab)의 한 요소라 셋 사이를 메뉴로 옮겨도 고른 기간이 그대로 남습니다.
 * 평가 보고서(/ops/eval)는 기간을 쓰지 않는 다른 요소라, 거기를 들렀다 돌아오면 처음 기간(24시간)으로 돌아갑니다.
 */
export function AdminPage() {
  const params = useParams()
  const tab: Tab = isTab(params.tab) ? params.tab : 'metrics'
  const [period, setPeriod] = useState<Period>({ kind: 'preset', preset: '24h' })
  // 기간은 적용할 때 한 번 시각으로 바꿔 둡니다. 다시 그릴 때마다 '지금'이 바뀌어 다시 불러오지 않게 합니다.
  const [range, setRange] = useState<Range>(() => toRange({ kind: 'preset', preset: '24h' })!)
  // 날짜 입력의 처음 값(지난 7일)과 고를 수 있는 마지막 날(오늘)은 화면을 열 때 한 번만 정합니다.
  const [today] = useState(() => ymd(new Date()))
  const [from, setFrom] = useState(() => ymd(new Date(Date.now() - 6 * 86_400_000)))
  const [to, setTo] = useState(today)
  const [rangeError, setRangeError] = useState<string | null>(null)

  function applyPreset(p: Period) {
    setPeriod(p)
    setRangeError(null)
    setRange(toRange(p)!)
  }

  function applyCustom(e: FormEvent) {
    e.preventDefault()
    const p: Period = { kind: 'custom', from, to }
    const r = toRange(p)
    if (!r) return setRangeError('시작·끝 날짜를 모두 고르고, 시작을 끝보다 늦지 않게 고르세요.')
    setPeriod(p)
    setRangeError(null)
    setRange(r)
  }

  if (!isTab(params.tab)) return <Navigate to="/ops/metrics" replace />
  const title = TABS.find((t) => t.id === tab)!.label
  return (
    <main className="admin" aria-labelledby="ops-title">
      <Toolbar title={title} titleId="ops-title">
        <div className="seg" role="group" aria-label="기간">
          {PRESETS.map((p) => (
            <button
              key={p.preset}
              type="button"
              className="seg__item"
              aria-pressed={period.kind === 'preset' && period.preset === p.preset}
              onClick={() => applyPreset({ kind: 'preset', preset: p.preset })}
            >
              최근 {p.label}
            </button>
          ))}
        </div>
      </Toolbar>
      <div className="admin__body">
        <form className="admin__custom" aria-label="날짜 범위" onSubmit={applyCustom}>
          <DateField className="admin__field" label="시작" value={from} max={today} invalid={!!rangeError} describedBy={rangeError ? 'admin-range-error' : undefined} onChange={setFrom} />
          <DateField className="admin__field" label="끝" value={to} max={today} invalid={!!rangeError} describedBy={rangeError ? 'admin-range-error' : undefined} onChange={setTo} />
          <Button type="submit" variant={period.kind === 'custom' ? 'primary' : 'secondary'}>
            날짜로 보기
          </Button>
        </form>
        <p className="admin__period" aria-live="polite">
          보는 기간: {period.kind === 'custom' ? formatDateRange(period.from, period.to) : `최근 ${PRESETS.find((p) => p.preset === period.preset)?.label}`}
        </p>
        {rangeError && (
          <p role="alert" id="admin-range-error" className="alert">
            {rangeError}
          </p>
        )}
        <div className="admin__panel">
          {tab === 'metrics' && <MetricsPanel range={range} />}
          {tab === 'egress' && <EgressPanel range={range} />}
          {tab === 'audit' && <AuditPanel range={range} />}
        </div>
      </div>
    </main>
  )
}
