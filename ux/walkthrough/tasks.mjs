// 페르소나별 핵심 과업입니다. 설명과 성공 기준의 근거는 ux/research/personas.md에 있습니다.
// 과업은 로그인 뒤 첫 화면(채팅)에서 시작하고, 화면에 보이는 이름으로만 요소를 찾습니다.
// 재설계 뒤에도 같은 과업과 기준으로 다시 돌립니다(#564). 화면 이름이 바뀌면 찾는 이름만 고칩니다.

const day = 86_400_000
const local = (d) => {
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}
const at = (offsetDays, hour) => {
  const d = new Date(Date.now() + offsetDays * day)
  d.setHours(hour, 0, 0, 0)
  return local(d)
}

// 기준 종류: 완료(과업의 끝 상태에 닿았는가), 확인(사람이 판단에 필요한 정보를 읽을 수 있었는가)
export const personas = {
  employee: { name: '직원', account: 'E1001', viewport: { width: 1280, height: 800 } },
  approver: { name: '결재자', account: 'E2001', viewport: { width: 1920, height: 1080 } },
  admin: { name: '관리자', account: 'E2008', viewport: { width: 1440, height: 900 } },
}

async function send(u, page, text) {
  const box = page.getByRole('textbox', { name: '메시지' })
  await u.fill(box, text, `메시지 입력: ${text}`)
  await u.press(box, 'Enter', '보내기(Enter)')
}

const txt = async (loc) => ((await loc.count()) ? (await loc.first().innerText()).replace(/\s+/g, ' ') : '')

export const tasks = [
  {
    id: 'E1',
    persona: 'employee',
    title: '영수증 사진으로 경비 정산 올리기',
    goal: '어제 팀 점심 영수증으로 경비 정산을 올린다. 올리기 전에 금액·날짜·가맹점이 영수증과 맞는지 본다.',
    criteria: [
      ['완료', '경비 정산을 실행했다'],
      ['확인', '금액이 원 단위 쉼표 형식(42,000원)으로 보인다'],
      ['확인', '값 이름이 한국어(가맹점·사용일·금액)로 보인다'],
      ['확인', '누가 결재하는지(결재선)가 보인다'],
      ['확인', '사진에서 읽은 값이라 확인이 필요하다는 표시가 보인다'],
    ],
    async run(u, page, { receipt, judge }) {
      await u.upload(page.getByRole('button', { name: '사진 첨부' }), [receipt], '사진 첨부')
      await send(u, page, '이 영수증 팀 점심 식대로 경비 정산해 줘')
      const card = page.getByRole('region', { name: /실행 미리보기/ })
      await u.see(card, '실행 미리보기 카드', 15000)
      await u.shot('preview')
      const t = await txt(card)
      judge('금액이 원 단위 쉼표 형식(42,000원)으로 보인다', /42,000\s*원/.test(t), t)
      judge('값 이름이 한국어(가맹점·사용일·금액)로 보인다', /가맹점/.test(t) && /사용일|날짜/.test(t), t)
      judge('누가 결재하는지(결재선)가 보인다', /결재선|팀장|서도윤/.test(t), t)
      judge('사진에서 읽은 값이라 확인이 필요하다는 표시가 보인다', /사진|이미지/.test(t), t)
      await u.click(card.getByRole('button', { name: '실행' }), '실행')
      await u.see(page.getByText(/올렸습니다/).last(), '결과 안내', 10000)
      await u.shot('done')
      judge('경비 정산을 실행했다', true)
    },
  },
  {
    id: 'E2',
    persona: 'employee',
    title: '회의실을 예약했다가 되돌리기',
    goal: '내일 오후 회의실을 잡았다가, 회의가 취소되어 예약을 되돌린다.',
    criteria: [
      ['완료', '예약을 되돌렸다'],
      ['확인', '예약한 회의실·시각이 결과에 보인다'],
      ['확인', '되돌린 뒤 되돌렸다는 표시가 보인다'],
    ],
    async run(u, page, { judge }) {
      await send(u, page, '내일 오후 2시에 회의실 예약해 줘')
      const done = page.getByRole('region', { name: '실행한 일' })
      await u.see(done, '실행한 일 카드', 10000)
      const t = await txt(done)
      judge('예약한 회의실·시각이 결과에 보인다', /회의실/.test(t) && /\d{1,2}:\d{2}/.test(t), t)
      await u.click(done.getByRole('button', { name: '되돌리기' }), '되돌리기')
      await u.see(done.getByText('되돌림'), '되돌림 표시')
      await u.shot('undone')
      judge('되돌린 뒤 되돌렸다는 표시가 보인다', true)
      judge('예약을 되돌렸다', true)
    },
  },
  {
    id: 'E3',
    persona: 'employee',
    title: '연차 규정을 묻고 근거 조문 확인하기',
    goal: '연차가 몇 년차에 늘어나는지 묻고, 답이 어느 규정 몇 조에서 왔는지 확인한다.',
    criteria: [
      ['완료', '답과 근거 조문을 읽었다'],
      ['확인', '근거가 펼치지 않아도 있다는 것이 보인다'],
      ['확인', '확인되지 않은 인용이 구별되어 보인다'],
    ],
    async run(u, page, { judge }) {
      await send(u, page, '연차는 몇 년차부터 늘어나? 규정 근거도 알려 줘')
      const log = page.getByRole('log')
      const cites = log.getByText(/근거 \d+건/)
      await u.see(cites, '근거 접힘 줄', 10000)
      judge('근거가 펼치지 않아도 있다는 것이 보인다', true)
      await u.click(cites, '근거 펼치기')
      await u.see(log.getByText(/제20조/), '조문 번호')
      await u.shot('citations')
      const t = await txt(log)
      judge('확인되지 않은 인용이 구별되어 보인다', /확인\s*(안|못|되지)|미확인/.test(t), t)
      judge('답과 근거 조문을 읽었다', true)
    },
  },
  {
    id: 'E4',
    persona: 'employee',
    title: '내가 올린 휴가 결재가 어디까지 갔는지 보기',
    goal: '지난번에 올린 연차 휴가 결재를 누가 아직 안 했는지 확인한다.',
    criteria: [
      ['완료', '올린 결재 문서를 열었다'],
      ['확인', '지금 누구 차례인지 보인다'],
      ['확인', '휴가 기간·종류가 한국어 이름으로 보인다'],
    ],
    async run(u, page, { judge }) {
      await u.click(page.getByRole('link', { name: '승인함' }), '승인함으로 이동')
      await u.click(page.getByRole('tab', { name: '올린 것' }), '올린 것 탭')
      await u.click(page.getByRole('button', { name: /연차 휴가 신청/ }), '문서 열기')
      const doc = page.getByRole('region', { name: /결재 문서/ })
      await u.see(doc, '결재 문서 상세')
      await u.shot('doc')
      const t = await txt(doc)
      judge('지금 누구 차례인지 보인다', /서도윤/.test(t) && /대기|차례|진행/.test(t), t)
      judge('휴가 기간·종류가 한국어 이름으로 보인다', /시작일/.test(t) && /종류/.test(t) && !/start_date|leave_type/.test(t), t)
      judge('올린 결재 문서를 열었다', true)
    },
  },
  {
    id: 'E5',
    persona: 'employee',
    title: '잘못 올린 반차 결재를 회수하기',
    goal: '날짜를 잘못 적은 반차 결재를 회수한다. 되돌릴 수 없는 일인지 알고 실행한다.',
    criteria: [
      ['완료', '회수를 실행했다'],
      ['확인', '되돌릴 수 없다는 경고가 실행 전에 보인다'],
      ['확인', '무엇이 어떻게 바뀌는지 한국어로 보인다'],
    ],
    async run(u, page, { judge }) {
      await send(u, page, '11월 24일 오후 반차 결재 회수해 줘')
      const card = page.getByRole('region', { name: /실행 미리보기/ })
      await u.see(card, '실행 미리보기 카드', 10000)
      await u.shot('preview')
      const t = await txt(card)
      judge('되돌릴 수 없다는 경고가 실행 전에 보인다', /되돌릴 수 없/.test(t), t)
      judge('무엇이 어떻게 바뀌는지 한국어로 보인다', !/\b(status|pending|withdrawn|approval)\b/.test(t), t)
      await u.click(card.getByRole('button', { name: '실행' }), '실행')
      await u.see(page.getByText(/회수했습니다/).last(), '결과 안내', 10000)
      await u.shot('done')
      judge('회수를 실행했다', true)
    },
  },
  {
    id: 'A1',
    persona: 'approver',
    title: '내 차례인 휴가 결재 승인하기',
    goal: '팀원의 연차 휴가 결재를 기간과 사유를 보고 승인한다.',
    criteria: [
      ['완료', '결재를 승인했다'],
      ['확인', '승인 전에 기간·종류·사유가 보인다'],
      ['확인', '승인한 문서가 처리함에 있다'],
    ],
    async run(u, page, { judge }) {
      await u.click(page.getByRole('link', { name: '승인함' }), '승인함으로 이동')
      await u.click(page.getByRole('button', { name: /연차 휴가 신청/ }), '문서 열기')
      const doc = page.getByRole('region', { name: /결재 문서/ })
      await u.see(doc, '결재 문서 상세')
      await u.shot('doc')
      const t = await txt(doc)
      judge('승인 전에 기간·종류·사유가 보인다', /11-27|11\/27|11월 27일|11\. 27/.test(t) && /연차/.test(t) && /개인 사정/.test(t), t)
      await u.click(doc.getByRole('button', { name: '승인' }), '승인')
      await u.see(page.getByRole('status'), '처리 안내')
      await u.click(page.getByRole('tab', { name: '처리함' }), '처리함 탭')
      const found = await page
        .getByRole('tabpanel', { name: '처리함' })
        .getByRole('button', { name: /연차 휴가 신청/ })
        .waitFor({ timeout: 5000 })
        .then(() => true, () => false)
      await u.shot('done')
      judge('승인한 문서가 처리함에 있다', found)
      judge('결재를 승인했다', true)
    },
  },
  {
    id: 'A2',
    persona: 'approver',
    title: '대결로 들어온 경비 정산 승인하기',
    goal: '출장 간 재무팀장 대신 맡은 경비 정산을 금액을 보고 승인한다. 누구 대신 하는지 확인한다.',
    criteria: [
      ['완료', '대결 문서를 승인했다'],
      ['확인', '원 결재자(누구 대신인지)가 보인다'],
      ['확인', '금액이 원 단위 쉼표 형식으로 보인다'],
      ['확인', '이 결재 다음 단계(누가 이어 받는지)가 보인다'],
    ],
    async run(u, page, { judge }) {
      await u.click(page.getByRole('link', { name: '승인함' }), '승인함으로 이동')
      await u.click(page.getByRole('tab', { name: '대결' }), '대결 탭')
      await u.click(page.getByRole('button', { name: /출장 경비/ }), '문서 열기')
      const doc = page.getByRole('region', { name: /결재 문서/ })
      await u.see(doc, '결재 문서 상세')
      await u.shot('doc')
      const t = await txt(doc)
      judge('원 결재자(누구 대신인지)가 보인다', /윤서진/.test(t), t)
      judge('금액이 원 단위 쉼표 형식으로 보인다', /320,000/.test(t), t)
      judge('이 결재 다음 단계(누가 이어 받는지)가 보인다', /임채원/.test(t), t)
      await u.click(doc.getByRole('button', { name: '승인' }), '승인')
      await u.see(page.getByRole('status'), '처리 안내')
      await u.shot('done')
      judge('대결 문서를 승인했다', true)
    },
  },
  {
    id: 'A3',
    persona: 'approver',
    title: '출장 동안 휴가 결재만 팀원에게 맡기기',
    goal: '내일부터 사흘 출장이라 그동안 휴가 신청 결재만 한지우에게 맡긴다.',
    criteria: [
      ['완료', '위임을 등록했다'],
      ['확인', '등록 전 미리보기에 대리인·기간·범위가 한국어로 보인다'],
      ['확인', '등록한 위임이 목록에 보인다'],
    ],
    async run(u, page, { judge }) {
      await u.click(page.getByRole('link', { name: '승인함' }), '승인함으로 이동')
      const panel = page.getByRole('complementary', { name: '대결 설정' })
      await u.fill(panel.getByRole('searchbox', { name: '이름으로 찾기' }), '한지우', '대리인 이름 찾기')
      await u.check(panel.getByRole('radio', { name: /한지우/ }), '대리인 고르기')
      await u.fill(panel.getByRole('textbox', { name: '시작' }), at(1, 9), '시작 시각')
      await u.fill(panel.getByRole('textbox', { name: '끝' }), at(3, 18), '끝 시각')
      await u.check(panel.getByRole('checkbox', { name: '모든 양식' }), '모든 양식 끄기', false)
      await u.check(panel.getByRole('checkbox', { name: '휴가 신청' }), '휴가 신청 고르기')
      await u.fill(panel.getByRole('textbox', { name: '사유' }), '출장', '사유')
      await u.click(panel.getByRole('button', { name: '미리보기' }), '미리보기')
      const pv = page.getByRole('region', { name: '위임 미리보기' })
      await u.see(pv, '위임 미리보기')
      await u.shot('preview')
      const t = await txt(pv)
      judge(
        '등록 전 미리보기에 대리인·기간·범위가 한국어로 보인다',
        /한지우/.test(t) && /휴가/.test(t) && !/\b(delegateId|formTypes|startsAt|emp-\d+)\b/.test(t),
        t,
      )
      await u.click(pv.getByRole('button', { name: '등록' }), '등록')
      await u.see(panel.getByText(/서도윤 → 한지우/), '위임 목록')
      await u.shot('done')
      judge('등록한 위임이 목록에 보인다', true)
      judge('위임을 등록했다', true)
    },
  },
  {
    id: 'M1',
    persona: 'admin',
    title: '외부 모델로 나간 요청에서 개인정보가 가려졌는지 보기',
    goal: '오늘 외부 모델로 나간 요청 중 전화번호가 가려진 건을 열어 실제로 가려졌는지 본다.',
    criteria: [
      ['완료', '외부 전송 기록 한 건의 본문을 열었다'],
      ['확인', '가린 자리가 본문에서 구별되어 보인다'],
      ['확인', '어느 직원·어느 대화의 요청인지 보인다'],
    ],
    async run(u, page, { judge }) {
      await u.click(page.getByRole('link', { name: '관리' }), '관리로 이동')
      await u.click(page.getByRole('tab', { name: '외부 전송 기록' }), '외부 전송 기록 탭')
      const row = page.getByRole('tabpanel').getByText(/가림 \d+곳: .*전화번호/)
      await u.click(row, '전화번호 가림 기록 펼치기')
      await u.shot('egress')
      const t = await txt(page.getByRole('tabpanel'))
      judge('가린 자리가 본문에서 구별되어 보인다', /\[(전화번호|PHONE|가림)[^\]]*\]|<[A-Z_]+>/.test(t), t.slice(0, 400))
      judge('어느 직원·어느 대화의 요청인지 보인다', /E\d{4}|emp-\d+|대화/.test(t), t.slice(0, 400))
      judge('외부 전송 기록 한 건의 본문을 열었다', true)
    },
  },
  {
    id: 'M2',
    persona: 'admin',
    title: '지난 7일 에이전트별 외부 비용과 차단 수 보기',
    goal: '주간 보고에 넣을 에이전트별 외부 비용과 정책 차단 수를 지난 7일 기준으로 찾는다.',
    criteria: [
      ['완료', '지난 7일 에이전트별 표를 봤다'],
      ['확인', '비용 단위가 분명하다(통화 표시)'],
      ['확인', '지금 보는 기간이 표 근처에 보인다'],
    ],
    async run(u, page, { judge }) {
      await u.click(page.getByRole('link', { name: '관리' }), '관리로 이동')
      await u.click(page.getByRole('button', { name: '최근 7일' }), '최근 7일')
      const table = page.getByRole('region', { name: '에이전트별 표' })
      await u.see(table, '에이전트별 표')
      await u.shot('metrics')
      const t = await txt(table)
      judge('비용 단위가 분명하다(통화 표시)', /\$|원|USD/.test(t), t.slice(0, 300))
      judge('지금 보는 기간이 표 근처에 보인다', /7일/.test(await txt(page.getByRole('main'))))
      judge('지난 7일 에이전트별 표를 봤다', true)
    },
  },
  {
    id: 'M3',
    persona: 'admin',
    title: '감사 로그에서 차단된 도구 실행 찾기',
    goal: '보안 점검 요청을 받아 최근 정책으로 차단된 도구 실행을 찾고 누가 했는지 본다.',
    criteria: [
      ['완료', '도구 차단 이벤트를 걸러 봤다'],
      ['확인', '직원이 이름으로 보인다'],
      ['확인', '에이전트·작업이 사람이 읽는 이름으로 보인다'],
    ],
    async run(u, page, { judge }) {
      await u.click(page.getByRole('link', { name: '관리' }), '관리로 이동')
      await u.click(page.getByRole('tab', { name: '감사 로그' }), '감사 로그 탭')
      await u.select(page.getByRole('combobox', { name: '종류' }), '도구 차단', '종류: 도구 차단')
      await u.click(page.getByRole('button', { name: '적용' }), '적용')
      const table = page.getByRole('region', { name: '감사 이벤트 표' })
      await u.see(table.getByText('도구 차단').nth(1), '걸러진 행')
      await u.shot('audit')
      const rows = await txt(table.locator('tbody'))
      judge('직원이 이름으로 보인다', /[가-힣]{2,4}/.test(rows) && !/emp-\d+/.test(rows), rows.slice(0, 300))
      judge('에이전트·작업이 사람이 읽는 이름으로 보인다', !/\b(assistant|hr|finance)\b/.test(rows), rows.slice(0, 300))
      judge('도구 차단 이벤트를 걸러 봤다', true)
    },
  },
  {
    id: 'M4',
    persona: 'admin',
    title: '평가 리포트에서 기대와 다른 시나리오 하나 열어 보기',
    goal: '이번 평가에서 이 프로젝트 조건이 기대와 다르게 끝난 시나리오를 찾아 이유를 본다.',
    criteria: [
      ['완료', '기대와 다른 시나리오의 회차 상세를 열었다'],
      ['확인', '시나리오가 사람이 읽는 제목으로 보인다'],
      ['확인', '왜 기대와 달랐는지 한 줄 이유가 보인다'],
    ],
    async run(u, page, { judge }) {
      await u.click(page.getByRole('link', { name: '평가' }), '평가로 이동')
      await u.select(page.getByRole('combobox', { name: '보기' }), '기대와 다른 회차가 있는 것만', '보기: 기대와 다름')
      const table = page.getByRole('region', { name: '시나리오별 결과 표' })
      // "이 프로젝트" 열(마지막 칸)이 기대와 다른 행을 눈으로 훑어 찾습니다.
      const row = table
        .getByRole('row')
        .filter({ has: page.getByRole('rowheader') })
        .filter({ has: page.locator('td:last-child', { hasText: '기대와 다름' }) })
        .first()
      const first = row.getByRole('rowheader').getByRole('button')
      await u.see(first, '이 프로젝트 열이 기대와 다른 행 찾기')
      const name = await txt(first)
      judge('시나리오가 사람이 읽는 제목으로 보인다', !/^[a-z0-9-]+$/.test(name.trim()), name)
      await u.click(first, '시나리오 펼치기')
      await u.shot('scenario')
      const t = await txt(page.locator(`[id="run-${name.trim()}"]`))
      judge('왜 기대와 달랐는지 한 줄 이유가 보인다', /이유|원인|때문|부족 .+않음/.test(t), t.slice(0, 400))
      judge('기대와 다른 시나리오의 회차 상세를 열었다', true)
    },
  },
]
