import type { Schemas } from '../api/client'

type Entry = Schemas['AgentRegistryEntry']

/** 직급 id의 이름(제조 팩 org.yaml grades). 모르는 id는 그대로 보여 줍니다. */
const GRADES: Record<string, string> = { staff: '팀원', team_leader: '팀장', division_head: '본부장', ceo: '대표이사' }
export const gradeName = (id: string) => GRADES[id] ?? id

export const UNIT_KIND: Record<Schemas['Unit']['kind'], string> = { division: '본부', team: '팀' }

export const RISK_ACTION: Record<Schemas['RiskAction'], string> = {
  auto: '바로 실행',
  auto_with_undo: '실행 뒤 되돌리기 안내',
  confirm: '실행 전 확인',
  deny: '금지',
}

export const OVERRIDE_WHEN: Record<'wide_scope' | 'always', string> = { wide_scope: '범위가 넓을 때', always: '항상' }

/** 팩 callable_by를 한 줄로 씁니다. */
export function callableByText(c: Entry['callableBy']): string {
  if (c === undefined) return '정보 없음'
  if (c === 'all') return '모든 직원'
  const parts = [
    c.roles?.length ? `역할 ${c.roles.join(', ')}` : null,
    c.units?.length ? `부서 ${c.units.join(', ')}` : null,
    c.grades?.length ? `직급 ${c.grades.map(gradeName).join(', ')}` : null,
  ].filter(Boolean)
  return parts.length ? parts.join(' 또는 ') : '정보 없음'
}
