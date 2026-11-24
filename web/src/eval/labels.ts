import type { Schemas } from '../api/client'
import type { BadgeTone } from '../components/Badge'

/** eval/harness/report.py의 이름과 같게 둡니다. 모르는 값은 그대로 보여 줍니다. */
const CONDITION: Record<string, string> = {
  no_guard: '장치 없음',
  write_blocked: '쓰기 차단',
  approve_all: '전건 승인',
  baseline_tools: '기성 도구 기본',
  full: '이 프로젝트',
}
export const conditionName = (c: string) => CONDITION[c] ?? c

const SET: Record<string, string> = { confirm: '확인 세트', dev: '개발 세트', normal: '정상 세트' }
export const setName = (s: string) => SET[s] ?? s

const CONCERN: Record<string, string> = {
  leak: '유출',
  out_of_scope_doc: '권한 밖 문서',
  cross_dept_bypass: '부서 간 우회',
  wrong_execution: '잘못된 실행',
  injection: '주입',
}
export const concernName = (t: string | null | undefined) => (t ? (CONCERN[t] ?? t) : '합계')

export const OUTCOME: Record<Schemas['row']['outcome'], { label: string; tone: BadgeTone }> = {
  incident: { label: '사고', tone: 'danger' },
  blocked: { label: '정책 차단', tone: 'warning' },
  completed: { label: '정상 완료', tone: 'success' },
  failed: { label: '실패로 끝남', tone: 'neutral' },
}

export const GROUP: Record<'general' | 'reactive' | 'all', string> = { general: '일반', reactive: '반응형', all: '전체' }

const pct1 = (x: number) => `${(x * 100).toFixed(1)}%`

/** "43/80 (53.8%, 42.2%~65.0%)". N이 0이면 "-" */
export function proportionText(p: Schemas['proportion'] | undefined): string {
  if (!p || p.N === 0) return '-'
  const rate = p.rate ?? p.n / p.N
  return p.low != null && p.high != null ? `${p.n}/${p.N} (${pct1(rate)}, ${pct1(p.low)}~${pct1(p.high)})` : `${p.n}/${p.N} (${pct1(rate)})`
}

const pp = (x: number) => `${x >= 0 ? '+' : ''}${(x * 100).toFixed(1)}%p`
/** "+22.5%p (+12.2~+31.9%p, 짝 80)". 짝이 없으면 "-" */
export function diffText(d: Schemas['pairedDiff'] | undefined): string {
  if (!d || d.pairs === 0) return '-'
  const n = (x: number) => `${x >= 0 ? '+' : ''}${(x * 100).toFixed(1)}`
  return `${pp(d.diff)} (${n(d.low)}~${n(d.high)}%p, 짝 ${d.pairs})`
}
