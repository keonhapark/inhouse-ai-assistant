import type { Schemas } from '../api/client'
import type { Risk } from '../components/Badge'
import { fieldName, gradeName, isMoneyKey, roleName } from '../display/names'

type Entry = Schemas['AgentRegistryEntry']

export { gradeName } from '../display/names'

export const UNIT_KIND: Record<Schemas['Unit']['kind'], string> = { division: '본부', team: '팀' }

/** 위험 등급 표시 이름. components/Badge의 RiskBadge와 같은 말입니다 */
export const RISK_LABEL: Record<Risk, string> = { read: '조회', reversible_write: '실행 취소 가능', irreversible: '실행 취소 불가' }

/** 위험 정책의 실행 방식(copy-guide 1.2). 실행 취소 가능 여부는 위험 등급 이름이 따로 알립니다 */
export const RISK_ACTION: Record<Schemas['RiskAction'], string> = {
  auto: '바로 실행',
  auto_with_undo: '바로 실행',
  confirm: '실행 전 확인',
  deny: '하지 않음',
}

type Override = NonNullable<Entry['riskPolicy']['overrides']>[number]
const WHEN: Record<Override['when'], string> = { wide_scope: '범위가 넓을 때', always: '항상', arg_gt: '인자 조건이 맞을 때' }

/** 받침이 있으면 a, 없으면 b(이/가, 은/는). 한글이 아니면 b */
export function josa(word: string, a: string, b: string): string {
  const c = word.charCodeAt(word.length - 1)
  return c >= 0xac00 && c <= 0xd7a3 && (c - 0xac00) % 28 !== 0 ? a : b
}

/** 위험 정책 예외의 조건을 한 구절로 씁니다. arg_gt는 "금액이 1,000,000원보다 클 때"처럼 씁니다. */
export function overrideWhen(o: Pick<Override, 'when' | 'arg' | 'gt'>): string {
  if (o.when === 'arg_gt' && o.arg && typeof o.gt === 'number') {
    const name = fieldName(o.arg)
    const money = isMoneyKey(o.arg)
    return `${name}${josa(name, '이', '가')} ${o.gt.toLocaleString('ko-KR')}${money ? '원' : ''}보다 클 때`
  }
  return WHEN[o.when] ?? o.when
}

/** 팩 callable_by를 한 줄로 씁니다. */
export function callableByText(c: Entry['callableBy']): string {
  if (c === undefined) return '정보 없음'
  if (c === 'all') return '모든 직원'
  const parts = [
    c.roles?.length ? `역할 ${c.roles.map(roleName).join(', ')}` : null,
    c.units?.length ? `부서 ${c.units.join(', ')}` : null,
    c.grades?.length ? `직급 ${c.grades.map(gradeName).join(', ')}` : null,
  ].filter(Boolean)
  return parts.length ? parts.join(' 또는 ') : '정보 없음'
}
