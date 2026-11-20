import type { Schemas } from '../api/client'

type Change = Schemas['Change']
export type ChangeRow = { field: string; before?: string; after?: string }

const ISO_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/
const ymdhm = new Intl.DateTimeFormat('ko-KR', {
  year: 'numeric',
  month: 'numeric',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

function text(v: unknown): string {
  if (v === null || v === undefined) return '없음'
  // 날짜·시각 문자열은 현지 시각으로 보여 줍니다.
  if (typeof v === 'string' && ISO_DATETIME.test(v)) return ymdhm.format(new Date(v))
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

/** 미리보기의 바뀌는 값을 필드별 "전 → 후"로 폅니다. 같은 값은 뺍니다. */
export function changeRows(c: Change): ChangeRow[] {
  const before = c.before ?? {}
  const after = c.after ?? {}
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])]
  return keys
    .filter((k) => c.op !== 'update' || text(before[k]) !== text(after[k]))
    .map((k) => ({
      field: k,
      before: c.op === 'create' ? undefined : text(before[k]),
      after: c.op === 'delete' ? undefined : text(after[k]),
    }))
}

const OP = { create: '새로 만듦', update: '바꿈', delete: '지움' } as const
export const opLabel = (op: Change['op']) => OP[op]

const hm = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })
export const formatTime = (iso: string) => hm.format(new Date(iso))
