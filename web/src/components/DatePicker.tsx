import * as Popover from '@radix-ui/react-popover'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { addDays, addMonths, koDate, koDateSpoken, koHour, pad, parseYmd, toYmd, WEEK } from '../display/dates'

/**
 * 한국식 날짜 고르개(ux/design-system.md 3.5, heuristics H-D2). 날짜는 "2026. 11. 24.(화)", 시는 "오후 2시"로 보입니다.
 * 브라우저 기본 date·datetime-local은 언어에 따라 미국식(11/22/2026, 10:00 PM)으로 보여 쓰지 않습니다.
 * 값은 기본 입력과 같은 꼴(YYYY-MM-DD, YYYY-MM-DDTHH:mm)이라 부르는 쪽은 그대로 씁니다.
 * 달력은 WAI-ARIA 날짜 고르개 대화상자 패턴입니다: 화살표 하루·한 주, PageUp·PageDown 한 달, Home·End 주의 처음·끝, Enter로 고름.
 */


type FieldProps = {
  label: string
  /** 감싸는 요소의 클래스(화면의 입력칸 묶음 스타일) */
  className?: string
  min?: string
  max?: string
  invalid?: boolean
  describedBy?: string
  disabled?: boolean
}

/** 날짜만 고릅니다. value는 YYYY-MM-DD 또는 빈 문자열 */
export function DateField({ value, onChange, ...rest }: FieldProps & { value: string; onChange(v: string): void }) {
  const labelId = useId()
  return (
    <div className={['datefield', rest.className].filter(Boolean).join(' ')} role="group" aria-labelledby={labelId}>
      <span id={labelId} className="datefield__label">
        {rest.label}
      </span>
      <Calendar labelId={labelId} value={value} onChange={onChange} {...rest} />
    </div>
  )
}

const HOURS = Array.from({ length: 24 }, (_, h) => pad(h))
const MINUTES = Array.from({ length: 6 }, (_, i) => pad(i * 10))

/** 날짜와 시각(오전·오후 시, 10분 단위)을 고릅니다. 값은 24시간제입니다. value는 YYYY-MM-DDTHH:mm 또는 빈 문자열 */
export function DateTimeField({ value, onChange, defaultTime = '09:00', ...rest }: FieldProps & { value: string; onChange(v: string): void; defaultTime?: string }) {
  const labelId = useId()
  const [date = '', time = ''] = value.split('T')
  const [hh, mm] = (time || defaultTime).split(':')
  // 값이 10분 단위가 아니면(예전에 넣은 값) 그 분도 고를 수 있게 둡니다
  const minutes = MINUTES.includes(mm) ? MINUTES : [...MINUTES, mm].sort()
  const set = (d: string, h: string, m: string) => onChange(d ? `${d}T${h}:${m}` : '')
  return (
    <div className={['datefield', rest.className].filter(Boolean).join(' ')} role="group" aria-labelledby={labelId}>
      <span id={labelId} className="datefield__label">
        {rest.label}
      </span>
      <span className="datefield__row">
        <Calendar labelId={labelId} value={date} onChange={(d) => set(d, hh, mm)} {...rest} />
        <select className="datefield__time" aria-label={`${rest.label} 시`} value={hh} disabled={rest.disabled || !date} onChange={(e) => set(date, e.target.value, mm)}>
          {HOURS.map((h) => (
            <option key={h} value={h}>
              {koHour(Number(h))}
            </option>
          ))}
        </select>
        <select className="datefield__time" aria-label={`${rest.label} 분`} value={mm} disabled={rest.disabled || !date} onChange={(e) => set(date, hh, e.target.value)}>
          {minutes.map((m) => (
            <option key={m} value={m}>
              {m}분
            </option>
          ))}
        </select>
      </span>
    </div>
  )
}

type CalendarProps = Omit<FieldProps, 'className'> & { labelId: string; value: string; onChange(v: string): void }

function Calendar({ labelId, label, value, onChange, min, max, invalid, describedBy, disabled }: CalendarProps) {
  const valueId = useId()
  const gridId = useId()
  const [open, setOpen] = useState(false)
  // 달력에서 초점을 둔 날. 달력에 보이는 달도 이 날로 정합니다
  const [focus, setFocus] = useState<Date>(() => parseYmd(value) ?? new Date())
  const gridRef = useRef<HTMLTableElement>(null)
  const moved = useRef(false)
  const selected = parseYmd(value)
  // 오늘은 열 때마다 다시 읽습니다(그리는 동안 시계를 읽지 않게, 자정을 넘겨도 맞게)
  const [today, setToday] = useState(() => toYmd(new Date()))
  const outOfRange = (ymd: string) => (!!min && ymd < min) || (!!max && ymd > max)

  // 키보드로 옮긴 날에 초점을 둡니다(달이 바뀌어 새로 그린 뒤에도)
  useEffect(() => {
    if (!open || !moved.current) return
    moved.current = false
    gridRef.current?.querySelector<HTMLButtonElement>(`[data-date="${toYmd(focus)}"]`)?.focus()
  }, [open, focus])

  function onOpenChange(next: boolean) {
    if (next) {
      // 값이 없으면 오늘을, 오늘이 고를 수 있는 범위 밖이면 가장 가까운 끝 날을 엽니다
      const now = toYmd(new Date())
      const start = min && now < min ? min : max && now > max ? max : now
      setToday(now)
      setFocus(parseYmd(value) ?? parseYmd(start) ?? new Date())
    }
    setOpen(next)
  }

  function move(d: Date) {
    moved.current = true
    setFocus(d)
  }

  function pick(ymd: string) {
    if (outOfRange(ymd)) return
    onChange(ymd)
    setOpen(false)
  }

  function onKey(e: KeyboardEvent) {
    // Alt+← 같은 브라우저 단축키는 그대로 둡니다
    if (e.altKey || e.ctrlKey || e.metaKey) return
    const day = focus.getDay()
    const next =
      e.key === 'ArrowLeft' ? addDays(focus, -1)
      : e.key === 'ArrowRight' ? addDays(focus, 1)
      : e.key === 'ArrowUp' ? addDays(focus, -7)
      : e.key === 'ArrowDown' ? addDays(focus, 7)
      : e.key === 'PageUp' ? addMonths(focus, e.shiftKey ? -12 : -1)
      : e.key === 'PageDown' ? addMonths(focus, e.shiftKey ? 12 : 1)
      : e.key === 'Home' ? addDays(focus, -day)
      : e.key === 'End' ? addDays(focus, 6 - day)
      : null
    if (!next) return
    e.preventDefault()
    move(next)
  }

  // 보이는 달의 첫 주 일요일부터 6주를 그립니다
  const first = new Date(focus.getFullYear(), focus.getMonth(), 1)
  const start = addDays(first, -first.getDay())
  const weeks = Array.from({ length: 6 }, (_, w) => Array.from({ length: 7 }, (_, i) => addDays(start, w * 7 + i)))
  const title = `${focus.getFullYear()}년 ${focus.getMonth() + 1}월`

  return (
    <Popover.Root open={open} onOpenChange={onOpenChange}>
      <Popover.Trigger
        type="button"
        className="datefield__trigger"
        aria-labelledby={`${labelId} ${valueId}`}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        disabled={disabled}
      >
        {/* 이름은 라벨 + 보이는 날짜 글자 그대로입니다(WCAG 2.5.3). 달력의 날 단추는 숫자만 보여 이름을 년월일 요일로 둡니다 */}
        <span id={valueId} className={selected ? undefined : 'datefield__placeholder'}>
          {selected ? koDate(value) : '날짜 고르기'}
        </span>
        <CalendarDays aria-hidden />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          className="popover datepicker"
          role="dialog"
          aria-label={`${label} 날짜 고르기`}
          align="start"
          sideOffset={6}
          onOpenAutoFocus={(e) => {
            // 열면 고른 날(없으면 오늘)에 초점을 둡니다
            e.preventDefault()
            gridRef.current?.querySelector<HTMLButtonElement>('[tabindex="0"]')?.focus()
          }}
        >
          <div className="datepicker__head">
            <button type="button" className="icon-btn" aria-label="이전 달" onClick={() => setFocus(addMonths(focus, -1))}>
              <ChevronLeft aria-hidden />
            </button>
            <h3 id={gridId} className="datepicker__title" aria-live="polite">
              {title}
            </h3>
            <button type="button" className="icon-btn" aria-label="다음 달" onClick={() => setFocus(addMonths(focus, 1))}>
              <ChevronRight aria-hidden />
            </button>
          </div>
          <table ref={gridRef} role="grid" aria-labelledby={gridId} className="datepicker__grid" onKeyDown={onKey}>
            <thead>
              <tr>
                {WEEK.map((w) => (
                  <th key={w} scope="col" abbr={`${w}요일`}>
                    {w}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {weeks.map((week) => (
                <tr key={toYmd(week[0])}>
                  {week.map((d) => {
                    const ymd = toYmd(d)
                    const isSel = !!selected && ymd === toYmd(selected)
                    const off = d.getMonth() !== focus.getMonth()
                    return (
                      <td key={ymd} role="gridcell" aria-selected={isSel}>
                        <button
                          type="button"
                          data-date={ymd}
                          tabIndex={ymd === toYmd(focus) ? 0 : -1}
                          className={off ? 'datepicker__day is-off' : 'datepicker__day'}
                          // 선택 상태는 gridcell의 aria-selected를 읽지 않는 화면 낭독기가 많아 이름에도 붙입니다
                          aria-label={isSel ? `${koDateSpoken(ymd)}, 선택됨` : koDateSpoken(ymd)}
                          aria-current={ymd === today ? 'date' : undefined}
                          aria-disabled={outOfRange(ymd) || undefined}
                          onClick={() => pick(ymd)}
                        >
                          {d.getDate()}
                        </button>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
