/** 관리자 콘솔의 기간. 미리 정한 길이 또는 날짜 범위(끝 날짜 포함)입니다. */
export type Preset = '24h' | '7d' | '30d'
export type Period = { kind: 'preset'; preset: Preset } | { kind: 'custom'; from: string; to: string }

export const PRESETS: { preset: Preset; label: string; hours: number }[] = [
  { preset: '24h', label: '24시간', hours: 24 },
  { preset: '7d', label: '7일', hours: 24 * 7 },
  { preset: '30d', label: '30일', hours: 24 * 30 },
]

/**
 * 기간을 API의 since·until(ISO)로 바꿉니다. 날짜 범위는 브라우저 시간대의 from 0시부터 to 다음 날 0시까지입니다.
 * 날짜가 비었거나 from이 to보다 늦으면 null입니다.
 */
export function toRange(p: Period, now = new Date()): { since: string; until: string } | null {
  if (p.kind === 'preset') {
    const hours = PRESETS.find((x) => x.preset === p.preset)?.hours ?? 24
    return { since: new Date(now.getTime() - hours * 3_600_000).toISOString(), until: now.toISOString() }
  }
  const from = localMidnight(p.from)
  const to = localMidnight(p.to)
  if (!from || !to || from > to) return null
  to.setDate(to.getDate() + 1)
  return { since: from.toISOString(), until: to.toISOString() }
}

function localMidnight(ymd: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd)
  if (!m) return null
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  return Number.isNaN(d.getTime()) ? null : d
}

/** 오늘 날짜(YYYY-MM-DD, 브라우저 시간대) */
export function ymd(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
