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
  {
    id: 'emp-2008',
    employeeNo: 'E2008',
    name: '권나래',
    unitId: 'it-ops',
    unitName: 'IT운영팀',
    grade: 'staff',
    email: 'e2008@example.test',
    roles: ['employee', 'auditor'],
    hiredOn: '2021-01-04',
  },
]

/** 결재선·대리인·조직도용 직원 목록. 이름은 지어낸 것이고, 부서는 제조 팩 org.yaml과 같습니다. */
type Person = { name: string; unitId: string; unitName: string; grade: string }
export const directory: Record<string, Person> = {
  'emp-1001': { name: '한지우', unitId: 'hr', unitName: '인사팀', grade: 'staff' },
  'emp-1002': { name: '박하늘', unitId: 'hr', unitName: '인사팀', grade: 'staff' },
  'emp-2001': { name: '서도윤', unitId: 'hr', unitName: '인사팀', grade: 'team_leader' },
  'emp-2002': { name: '윤서진', unitId: 'finance', unitName: '재무팀', grade: 'team_leader' },
  'emp-2003': { name: '오민재', unitId: 'finance', unitName: '재무팀', grade: 'staff' },
  'emp-2004': { name: '정다은', unitId: 'general-affairs', unitName: '총무팀', grade: 'team_leader' },
  'emp-2005': { name: '강태오', unitId: 'procurement', unitName: '구매자재팀', grade: 'team_leader' },
  'emp-2006': { name: '조유나', unitId: 'procurement', unitName: '구매자재팀', grade: 'staff' },
  'emp-2007': { name: '배준호', unitId: 'it-ops', unitName: 'IT운영팀', grade: 'team_leader' },
  'emp-2008': { name: '권나래', unitId: 'it-ops', unitName: 'IT운영팀', grade: 'staff' },
  'emp-3001': { name: '임채원', unitId: 'mgmt', unitName: '경영지원본부', grade: 'division_head' },
  'emp-3002': { name: '노승현', unitId: 'production-div', unitName: '생산본부', grade: 'division_head' },
  'emp-9001': { name: '문성호', unitId: 'ceo-office', unitName: '대표이사실', grade: 'ceo' },
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
  {
    id: 'finance',
    name: '재무',
    description: '경비 정산 결재 요청과 회수, 재무 규정(여비·경비) 질의를 맡습니다.',
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
