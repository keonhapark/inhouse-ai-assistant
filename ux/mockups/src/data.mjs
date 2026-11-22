// 시안에 채우는 가상 데이터입니다. 회사·사람·가게는 모두 지어낸 것이고, 사업자번호는 예시 번호입니다.
// 이야기 하나로 이어집니다: 직원 오지현이 팀 점심 영수증으로 경비 정산을 올리고(AI 비서),
// 팀장 서도윤이 결재 화면에서 그 문서를 받아 승인합니다(결재).

export const company = { name: '한결정밀', product: '사내 AI 비서' }

export const employee = { name: '오지현', team: '생산관리팀', title: '팀원', initials: '지현' }
export const approver = { name: '서도윤', team: '생산관리팀', title: '팀장', initials: '도윤' }

export const nav = [
  {
    group: '업무',
    items: [
      { key: 'chat', label: 'AI 비서', icon: 'sparkles' },
      { key: 'approvals', label: '결재', icon: 'file-check', count: 3 },
      { key: 'delegations', label: '대결 설정', icon: 'arrow-right-left' },
    ],
  },
  {
    group: '회사',
    items: [
      { key: 'org', label: '조직도', icon: 'building-2' },
      { key: 'agents', label: 'AI 에이전트', icon: 'bot' },
    ],
  },
]

export const conversations = [
  { title: '팀 점심 식대 정산', agent: '재무', status: '확인 기다림', tone: 'attention', when: '12:41', active: true },
  { title: '3층 소회의실 예약', agent: '전사 비서', status: '예약함', tone: 'approved', when: '어제' },
  { title: '11/24 반차 결재 회수', agent: '인사', status: '회수함', tone: 'neutral', when: '11월 20일' },
  { title: '창원 출장 숙박비 한도', agent: '재무', status: null, when: '11월 18일' },
  { title: '올해 남은 연차', agent: '인사', status: null, when: '11월 15일' },
]

export const chat = {
  agent: '재무',
  userText: '어제 팀 점심 영수증이야. 식대로 경비 정산 올려 줘',
  answer:
    '영수증에서 가맹점, 사용일, 금액을 읽었습니다. 1인당 10,500원으로 식대 한도(1인 15,000원) 안이라 팀장 결재 한 단계로 올라갑니다. 값이 영수증과 맞는지 확인해 주세요.',
}

export const expense = {
  action: '경비 정산 올리기',
  fields: [
    ['가맹점', '가온식당 성수점'],
    ['사용일', '2026. 11. 21. (금)'],
    ['금액', '42,000원'],
    ['용도', '식대 · 팀 점심 4명'],
    ['사업자번호', '123-45-67890'],
  ],
  amount: '42,000원',
  policy: { ok: true, text: '식대 한도 안', detail: '1인 10,500원 / 한도 15,000원' },
  line: [
    { name: '오지현', role: '요청', state: 'done', at: '어제 12:44' },
    { name: '서도윤', role: '팀장 결재 대기', state: 'current' },
  ],
  expiresIn: '9분 남음',
}

export const receipt = {
  store: '가온식당 성수점',
  bizNo: '123-45-67890',
  address: '서울 성동구 성수이로 00',
  at: '2026-11-21 12:38',
  items: [
    ['점심 정식', 4, '40,000'],
    ['공깃밥 추가', 2, '2,000'],
  ],
  total: '42,000',
  card: '법인카드 ****-1460',
}

export const approvalTabs = [
  { label: '받은 결재', count: 3, active: true },
  { label: '대결로 받은 결재', count: 1 },
  { label: '처리한 결재' },
  { label: '올린 결재' },
]

export const approvals = [
  { form: '경비 정산', icon: 'receipt', title: '팀 점심 식대', requester: '오지현', amount: '42,000원', received: '오늘 12:44', wait: '18분', selected: true, tag: '사진에서 읽음' },
  { form: '휴가 신청', icon: 'calendar-clock', title: '연차 11. 27.~11. 28. (2일)', requester: '김태윤', amount: '–', received: '어제 17:02', wait: '1일' },
  { form: '구매 요청', icon: 'package', title: '오일 실 35×52×8 200개', requester: '박세영', amount: '380,000원', received: '11월 20일', wait: '2일', tag: '2단계' },
]

export const approvalDoc = {
  title: '팀 점심 식대',
  form: '경비 정산',
  docNo: 'EXP-0107',
  requester: { name: '오지현', team: '생산관리팀' },
  submitted: '2026년 11월 21일 12:44',
  fields: expense.fields,
  policy: expense.policy,
  source: 'AI 비서가 사진에서 읽고, 요청자가 확인한 뒤 올렸습니다.',
  line: [
    { name: '오지현', role: '요청', state: 'done', at: '어제 12:44' },
    { name: '서도윤', role: '내 차례', state: 'current' },
  ],
  confirm: '승인하면 이 결재가 끝나고 되돌릴 수 없습니다.',
}

// 운영 도구형 시안에서 표 밀도를 보여 주려고 같은 화면 아래에 두는 "오늘 처리한 결재"입니다.
export const doneToday = [
  { form: '휴가 신청', icon: 'calendar-clock', title: '오후 반차 11. 21.', requester: '김태윤', amount: '–', at: '09:12', result: ['approved', '승인'] },
  { form: '경비 정산', icon: 'receipt', title: '창원 출장 교통비', requester: '박세영', amount: '86,400원', at: '08:57', result: ['approved', '승인'] },
  { form: '구매 요청', icon: 'package', title: '측정용 버니어 캘리퍼스 2개', requester: '이준서', amount: '214,000원', at: '08:40', result: ['rejected', '반려'] },
  { form: '경비 정산', icon: 'receipt', title: '협력사 미팅 택시비', requester: '오지현', amount: '18,000원', at: '08:31', result: ['approved', '승인'] },
  { form: '휴가 신청', icon: 'calendar-clock', title: '연차 12. 1.', requester: '정하린', amount: '–', at: '08:05', result: ['approved', '승인'] },
]
