import type { Employee, Schemas } from '../api/client'

// 모의 서버용 지어낸 직원입니다. 비밀번호는 모두 'demo'입니다.
export const MOCK_PASSWORD = 'demo'

export const employees: Employee[] = [
  {
    id: 'emp-1001',
    employeeNo: 'E1001',
    name: '한지우',
    unitId: 'hr',
    unitName: '인사팀',
    grade: 'staff',
    email: 'e1001@example.test',
    roles: ['employee', 'hr_staff'],
    hiredOn: '2023-03-02',
  },
  {
    id: 'emp-2001',
    employeeNo: 'E2001',
    name: '서도윤',
    unitId: 'hr',
    unitName: '인사팀',
    grade: 'team_leader',
    email: 'e2001@example.test',
    roles: ['employee'],
    hiredOn: '2016-07-01',
  },
]

/** 로그인하지 않는 직원(결재선·대리인용). 이름은 지어낸 것입니다. */
export const directory: Record<string, { name: string; unitName: string }> = {
  'emp-1001': { name: '한지우', unitName: '인사팀' },
  'emp-1002': { name: '박하늘', unitName: '인사팀' },
  'emp-2001': { name: '서도윤', unitName: '인사팀' },
  'emp-2002': { name: '윤서진', unitName: '재무팀' },
  'emp-3001': { name: '임채원', unitName: '경영지원본부' },
}

export const agents: Schemas['AgentInfo'][] = [
  {
    id: 'assistant',
    name: '전사 비서',
    description: '공통 규정 질의, 회의실, 일반 안내를 맡고 맞는 부서 에이전트를 안내합니다.',
    modelPolicy: 'external_allowed',
    callable: true,
  },
  {
    id: 'hr',
    name: '인사',
    description: '휴가·반차 결재 요청과 회수, 결재 대결 등록·해지 요청, 인사 규정, 본인 휴가 잔여를 맡습니다.',
    modelPolicy: 'local_only',
    callable: true,
  },
]

export function tokenFor(e: Employee): string {
  return `mock.${e.id}`
}

export function employeeForToken(authorization: string | null): Employee | undefined {
  const token = authorization?.replace(/^Bearer /, '')
  return employees.find((e) => tokenFor(e) === token)
}
