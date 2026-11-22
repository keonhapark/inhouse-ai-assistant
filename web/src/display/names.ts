/**
 * 코드 이름 → 화면 이름 사전(#556). 계약(contracts/mcp/tools.json, 팩 org.yaml)에 표시 이름이 없어 web에 둡니다.
 * 모르는 이름은 그대로 돌려줘, 새 도구·역할이 생겨도 화면이 깨지지 않습니다.
 */

/** 도구 표시 이름. 세 팩(제조·금융·IT 서비스)의 도구 */
export const TOOL_LABELS: Record<string, string> = {
  hr_get_my_profile: '내 인사 정보 보기',
  org_search_employees: '동료 찾기',
  leave_get_balance: '연차 잔여 보기',
  leave_request: '휴가 신청',
  approval_list_mine: '내 결재 목록 보기',
  approval_get: '결재 문서 보기',
  approval_withdraw: '결재 회수',
  delegation_list: '대결 목록 보기',
  delegation_register: '대결 등록',
  delegation_revoke: '대결 해지',
  room_list_availability: '빈 회의실 찾기',
  room_list_my_reservations: '내 회의실 예약 보기',
  room_reserve: '회의실 예약',
  room_cancel_reservation: '회의실 예약 취소',
  policy_search: '규정 검색',
  expense_request: '경비 정산 올리기',
  purchase_request: '구매 요청 올리기',
  ticket_list: 'IT 티켓 목록 보기',
  ticket_get: 'IT 티켓 보기',
  ticket_create: 'IT 티켓 올리기',
  ticket_comment: 'IT 티켓 댓글 달기',
  incident_analyze: '장애 분석',
  defect_report_draft: '불량 보고서 초안 쓰기',
  defect_report_list: '불량 보고서 목록 보기',
  defect_report_get: '불량 보고서 보기',
  quote_draft: '견적 초안 쓰기',
  quote_list: '견적 목록 보기',
  quote_get: '견적 보기',
  item_search: '품목 찾기',
  customer_search: '고객사 찾기',
  loan_request: '여신 품의 올리기',
  effort_report: '공수 보고',
}
export const toolName = (name: string) => TOOL_LABELS[name] ?? name

/** 역할 표시 이름. 세 팩 org.yaml roles */
const ROLE_LABELS: Record<string, string> = {
  employee: '직원',
  hr_staff: '인사 담당',
  finance_staff: '재무 담당',
  quality_staff: '품질 확인',
  sales_staff: '영업 담당',
  it_admin: 'IT 관리자',
  auditor: '감사 조회',
  credit_officer: '여신 담당',
  compliance_officer: '내부통제 담당',
  project_staff: '프로젝트 수행',
  account_manager: '고객사 담당',
  service_desk: '운영 티켓 담당',
}
export const roleName = (id: string) => ROLE_LABELS[id] ?? id

/** 직급 표시 이름(세 팩 공통 grades) */
const GRADE_LABELS: Record<string, string> = { staff: '팀원', team_leader: '팀장', division_head: '본부장', ceo: '대표이사' }
export const gradeName = (id: string) => GRADE_LABELS[id] ?? id

/** 미리보기 변경 대상(Change.resource) */
const RESOURCE_LABELS: Record<string, string> = {
  approval_document: '결재 문서',
  approval: '결재 문서',
  delegation: '대결 위임',
  room_reservation: '회의실 예약',
  leave_balance: '연차',
  ticket: 'IT 티켓',
  ticket_comment: 'IT 티켓 댓글',
  defect_report: '불량 보고서',
  quote: '견적',
}
export const resourceName = (r: string) => RESOURCE_LABELS[r] ?? r

/**
 * erp 자원의 필드 표시 이름(contracts/openapi/erp.yaml). 결재 문서의 양식 필드는 양식 스키마의 title이 먼저입니다.
 * 도구 인자 이름(snake_case)도 같이 둡니다(위험 정책 예외의 arg).
 */
const FIELD_LABELS: Record<string, string> = {
  title: '제목',
  status: '상태',
  amount: '금액',
  total_amount: '합계',
  totalAmount: '합계',
  quantity: '수량',
  unitPrice: '단가',
  itemCode: '품목 코드',
  itemName: '품목',
  defectType: '불량 유형',
  severity: '심각도',
  location: '위치',
  lotNo: '로트 번호',
  description: '설명',
  confirmedBy: '확정한 사람',
  customerId: '고객사 ID',
  customerName: '고객사',
  lines: '품목 줄',
  validUntil: '유효 기한',
  note: '메모',
  category: '분류',
  priority: '우선순위',
  body: '내용',
  roomId: '회의실',
  startsAt: '시작',
  endsAt: '끝',
  attendees: '참석 인원',
  delegatorId: '맡긴 사람',
  delegateId: '대결자',
  scope: '범위',
  reason: '사유',
  annualTotal: '올해 연차',
  annualUsed: '사용',
  annualPending: '결재 중',
  annualRemaining: '남은 일수',
  formId: '양식',
  steps: '결재선',
}
export const fieldName = (key: string) => FIELD_LABELS[key] ?? key

/** 열거값 표시 이름(필드별). 결재 문서 상태·결재 단계 상태는 inbox/labels.ts */
const ENUM_LABELS: Record<string, Record<string, string>> = {
  status: {
    in_progress: '진행',
    pending: '대기',
    approved: '승인',
    rejected: '반려',
    withdrawn: '회수',
    draft: '초안',
    confirmed: '확정',
    cancelled: '취소',
    issued: '발행',
    open: '접수',
    resolved: '해결',
    closed: '닫힘',
    scheduled: '예정',
    active: '유효',
    expired: '만료',
    revoked: '해지',
  },
  severity: { minor: '경미', major: '중대', critical: '치명' },
  category: { incident: '장애', access_request: '계정·권한 요청', other: '그 밖의 요청' },
  priority: { low: '낮음', normal: '보통', high: '높음' },
}
export const enumName = (key: string, value: string) => ENUM_LABELS[key]?.[value] ?? value

/** 금액(원)인 필드·인자 이름: amount, total_amount, unit_price, totalAmount, unitPrice, maxAmount */
export const isMoneyKey = (key: string) => /(^|_)(amount|price)$|(Amount|Price)$/.test(key)
