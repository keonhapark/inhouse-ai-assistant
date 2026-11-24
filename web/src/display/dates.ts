/** 날짜 고르개(components/DatePicker)가 쓰는 날짜 계산과 한국식 표시 */

export const WEEK = ['일', '월', '화', '수', '목', '금', '토']
export const pad = (n: number) => String(n).padStart(2, '0')

/** Date → YYYY-MM-DD(브라우저 시간대) */
export const toYmd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

export function parseYmd(v: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(v)
  if (!m) return null
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  return d.getMonth() === Number(m[2]) - 1 ? d : null
}

/** 2026-11-23 → "2026년 11월 23일(월)" */
export function koDate(v: string): string {
  const d = parseYmd(v)
  return d ? `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일(${WEEK[d.getDay()]})` : ''
}

export const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n)
/** 달을 옮기되 날짜는 그 달의 마지막 날을 넘지 않게 합니다(1월 31일 → 2월 28일) */
export function addMonths(d: Date, n: number) {
  const last = new Date(d.getFullYear(), d.getMonth() + n + 1, 0).getDate()
  return new Date(d.getFullYear(), d.getMonth() + n, Math.min(d.getDate(), last))
}
