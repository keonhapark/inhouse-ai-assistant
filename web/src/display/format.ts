/**
 * 화면에 보이는 값의 한국어 형식(#556). 어느 화면 디자인이든 같이 씁니다(#558).
 * 날짜만 있는 값(YYYY-MM-DD)은 시간대를 타지 않게 UTC로 읽어 그대로 보여 줍니다.
 */

const YMD = /^(\d{4})-(\d{2})-(\d{2})$/
export const ISO_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/

const date = new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: 'numeric', day: 'numeric', timeZone: 'UTC' })
const weekday = new Intl.DateTimeFormat('ko-KR', { weekday: 'short', timeZone: 'UTC' })
const dateTime = new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
const hm = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })
const md = new Intl.DateTimeFormat('ko-KR', { month: 'long', day: 'numeric' })
const ymd = new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: 'numeric', day: 'numeric' })

/** 5800 → "5,800원". 값이 없으면 "–" */
export const formatWon = (n: number | null | undefined) => (n == null ? '–' : `${n.toLocaleString('ko-KR')}원`)

/** "2026-09-30" → "2026. 9. 30.(수)". 날짜 꼴이 아니면 그대로 */
export function formatDate(v: string): string {
  const m = YMD.exec(v)
  if (!m) return v
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]))
  // 없는 날(2026-02-30)은 Date가 다음 달로 넘기므로 되읽어 확인하고, 맞지 않으면 그대로 둡니다
  if (d.getUTCFullYear() !== +m[1] || d.getUTCMonth() !== +m[2] - 1 || d.getUTCDate() !== +m[3]) return v
  return `${date.format(d)}(${weekday.format(d)})`
}

/** ISO 시각 → "2026. 11. 22. 11:20"(현지 시각) */
export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : dateTime.format(d)
}

/** "YYYY-MM-DD" 두 개 → "2026. 11. 15.(일) ~ 2026. 11. 21.(토)" */
export const formatDateRange = (from: string, to: string) => `${formatDate(from)} ~ ${formatDate(to)}`

const sameDay = (a: Date, b: Date) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()

/** 목록에서 언제인지: 오늘이면 "오늘 11:20", 어제면 "어제 11:20", 올해면 "11월 20일", 다른 해면 "2025. 11. 20." */
export function formatWhen(iso: string, now = new Date()): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  if (sameDay(d, now)) return `오늘 ${hm.format(d)}`
  const y = new Date(now)
  y.setDate(now.getDate() - 1)
  if (sameDay(d, y)) return `어제 ${hm.format(d)}`
  return d.getFullYear() === now.getFullYear() ? md.format(d) : ymd.format(d)
}
