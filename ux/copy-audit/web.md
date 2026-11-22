# web/src 화면 문구 점검

기준: `ux/copy-guide.md`. 경로는 `web/src/` 기준입니다. `{…}`는 코드가 채우는 값입니다.
시험 파일·`src/test/`·`src/mocks/`·코드 주석은 범위에서 뺐습니다.

## 점검 표

| 파일:줄 | 지금 문구 | 고칠 문구 | 분류 | 근거 |
|---|---|---|---|---|
| chat/ChatPage.tsx:16 | 자동 선택(낱말) | 자동 선택 | 용어 불일치 | 1.2 에이전트를 고르는 방식(방식 이름은 관리 화면에만) |
| chat/ChatPage.tsx:302 | 에이전트 고르는 중 | AI 에이전트 고르는 중 | 용어 불일치 | 1.2 부서별 AI |
| chat/ChatPage.tsx:308 | 부서 에이전트 (선택 칸 라벨) | AI 에이전트 | 용어 불일치 | 1.2 부서별 AI |
| chat/ChatPage.tsx:314, org/AgentRegistryPage.tsx:79 | (로컬 모델만) / 로컬 모델만 | (사내 처리만) / 사내 처리만 | 직역투 | 1.2 사내 처리, 2.4 영어 단어 그대로 |
| chat/ChatPage.tsx:334 | 무엇을 도와드릴까요? 회의실 예약, 연차 규정처럼 물어보면 맞는 부서 에이전트가 답합니다. | 회의실 예약, 연차 규정처럼 물어보면 맞는 부서의 AI 에이전트가 답합니다. | AI 말투 | 2.4 과한 공손, 1.2 부서별 AI |
| chat/ChatPage.tsx:352 | 사진 {n}장 첨부(기록에는 사진을 남기지 않습니다) | 사진 {n}장 첨부 · 사진은 기록에 남기지 않습니다 | 어색함 | 2.4 불필요한 괄호 |
| chat/ChatPage.tsx:379 | 차단 (배지) | 처리할 수 없는 요청 | 용어 불일치 | 1.2 정책으로 막힘(직원 화면) |
| chat/ChatPage.tsx:394 | 다시 보내기 | 다시 시도 | 용어 불일치 | 1.3 다시 하기 |
| chat/ChatPage.tsx:408 | 미리보기 카드에서 실행하거나 취소하면 이어서 쓸 수 있습니다. | 실행 전 확인 카드에서 실행하거나 취소하면 이어서 쓸 수 있습니다. | 직역투 | 1.2 실행 전 확인, 2.4 영어 단어 그대로 |
| chat/ChatPage.tsx:447 | 메시지를 입력합니다. Enter로 보내고 Shift+Enter로 줄을 바꿉니다. (placeholder) | 메시지를 입력하세요. Enter로 보내고 Shift+Enter로 줄을 바꿉니다. | 어색함 | 2.1 할 일은 "~하세요" |
| chat/api.ts:39 | 서버 응답을 읽지 못했습니다. | 서버 응답을 읽지 못했습니다. 잠시 뒤 다시 시도해 주세요. | 어색함 | 2.3 오류는 무슨 일 + 할 일 |
| chat/api.ts:101 | 되돌리지 못했습니다. | 실행을 취소하지 못했습니다. | 직역투 | 1.2 실행 취소, 2.4 영어 단어 그대로 |
| chat/attachments.ts:61 | 사진은 한 번에 {MAX}장까지 붙일 수 있어 {over}장은 붙이지 않았습니다. | {over}장은 붙이지 않았습니다. 사진은 한 번에 {MAX}장까지 붙일 수 있습니다. | 어색함 | 2.3 결과 먼저 |
| chat/parts.tsx:32 | 근거 {n}건 | 근거 규정 {n}건 | 용어 불일치 | 1.2 답의 근거 |
| chat/parts.tsx:39 | 인용 확인 안 됨 | 원문 대조 안 됨 | 용어 불일치 | 1.2 인용이 원문과 맞는지 확인 못 함 |
| chat/parts.tsx:86 | 실행 미리보기: {작업} (aria-label) | 실행 전 확인: {작업} | 직역투 | 1.2 실행 전 확인, 2.4 |
| chat/parts.tsx:92 | 이미지에서 읽은 값(확인 필요) | 사진에서 읽은 값 | 용어 불일치 | 1.2 사진에서 읽은 값, 2.4 불필요한 괄호 |
| chat/parts.tsx:97 | 실행함 / 취소함 | 완료 / 취소 (취소 쪽은 확인 필요: 실행 취소 결과 "취소됨"과 구별할지) | 용어 불일치 | 1.2 실행 결과 표시, 2.5 한 개념에 한 배지 |
| chat/parts.tsx:99 | 더 결정할 수 없음 | 확인 필요(예: 실행할 수 없음) | 어색함 | 2.5 배지 글이 혼자 읽혀야 함 |
| chat/parts.tsx:103 | 만료됨 / 만료 {HH:MM} | 확인 시간 지남 / {HH:MM}까지 확인 | 용어 불일치 | 1.2 확인 카드의 남은 시간 |
| chat/parts.tsx:113 | 실행 (버튼) | {작업 표시 이름} (예: 경비 정산 상신, 결재 회수) | 용어 불일치 | 1.2 카드의 실행 버튼, 2.2 버튼 둘 다 동작 이름 |
| chat/parts.tsx:121 | 첨부한 사진에서 읽은 값이 들어 있을 수 있습니다. 금액·날짜 같은 값이 사진과 맞는지 확인한 뒤 실행해 주세요. | 금액·날짜가 첨부한 사진과 맞는지 확인한 뒤 실행해 주세요. | AI 말투 | 2.4 확신 흐리기, 1.2 사진에서 읽은 값 |
| chat/parts.tsx:124 | 실행하면 되돌릴 수 없습니다. | 실행하면 취소할 수 없습니다. | 직역투 | 1.2 실행 취소 가능/불가, 2.4 |
| chat/parts.tsx:222 | 되돌림 / 실행됨 | 취소됨 / 완료 | 직역투 | 1.2 실행 취소·실행 결과 표시, 2.5 |
| chat/parts.tsx:226 | 되돌리기 | 실행 취소 | 직역투 | 1.2 실행한 일을 원래대로, 2.4 |
| chat/parts.tsx:244 | 도구 실행: {표시 이름} `{코드 이름}` | {표시 이름} (예: 규정 검색), 코드 이름은 빼기 | 용어 불일치 | 1.2 에이전트가 부른 기능(코드 이름은 화면에 내지 않음) |
| chat/parts.tsx:248 | 성공 / 차단 / 오류 | 완료 / 처리할 수 없는 요청 / 오류 (확인 필요: 펼친 도구 줄의 배지라 길이) | 용어 불일치 | 1.2 실행 결과 표시·정책으로 막힘 |
| chat/thread.ts:163 | 요청을 처리할 수 없습니다. | 확인 필요: 이유 한 줄 + 다음 행동 한 줄 (예: 이 요청은 처리할 수 없습니다. 담당 부서에 문의하세요.) | 어색함 | 1.2 정책으로 막힘(이유와 다음 행동), 2.3 |
| chat/thread.ts:174 | 답을 만들지 못했습니다. | 답을 만들지 못했습니다. 다시 시도해 주세요. | 어색함 | 2.3 오류는 무슨 일 + 할 일 |
| components/Badge.tsx:13, components/Badge.tsx:14 | 되돌릴 수 있음 / 되돌릴 수 없음 | 실행 취소 가능 / 실행 취소 불가 | 직역투 | 1.2 실행 취소가 되는 일인지 |
| components/Badge.tsx:23 | 로컬에서 처리 | 사내 처리 | 직역투 | 1.2 사내 모델로 처리, 2.4 |
| display/conversation.ts:12 | 에이전트 미정 | AI 에이전트 미정 | 용어 불일치 | 1.2 부서별 AI |
| display/conversation.ts:13 | 승인 대기 | 확인 대기 | 용어 불일치 | 1.2 실행 전 확인(결재의 "승인"과 겹침) |
| display/names.ts:16 | 대결 등록 | 대결 지정 | 용어 불일치 | 1.1 부재 중 대신 결재 |
| display/names.ts:17 | 대결 해지 | 대결 해제 | 용어 불일치 | 1.1 대결 지정을 끝냄 |
| display/names.ts:23, display/names.ts:24, display/names.ts:38 | 경비 정산 올리기 / 구매 요청 올리기 / 여신 품의 올리기 | 경비 정산 상신 / 구매 요청 상신 / 여신 품의 상신 | 용어 불일치 | 1.1 기안·상신, 1.2 카드의 실행 버튼 |
| display/names.ts:27, display/names.ts:28, display/names.ts:30, display/names.ts:33 | IT 티켓 올리기 / IT 티켓 댓글 달기 / 불량 보고서 초안 쓰기 / 견적 초안 쓰기 | 확인 필요(예: IT 티켓 등록 / IT 티켓 댓글 / 불량 보고서 초안 작성 / 견적 초안 작성) | 어색함 | 2.2 버튼("~하기" 꼴, 1.2에 따라 버튼 이름이 됨), 1.4 표시 이름 |
| display/names.ts:48, display/names.ts:51, display/names.ts:54 | 품질 확인 / 감사 조회 / 프로젝트 수행 (역할 이름) | 확인 필요(다른 역할처럼 "○○ 담당" 꼴) | 어색함 | 1 머리말(같은 개념은 같은 말) |
| display/names.ts:68 | 대결 위임 | 대결 | 용어 불일치 | 1.1 "위임"은 쓰지 않음 |
| display/names.ts:100 | 품목 줄 | 품목 내역 | 직역투 | 2.4 직역투(line items) |
| display/names.ts:110 | 맡긴 사람 | 원 결재자 (확인 필요) | 용어 불일치 | 1.1 대결·후열(원 결재자) |
| display/names.ts:126, inbox/labels.ts:7, pages/DesignPage.tsx:44 | 진행 | 진행 중 | 용어 불일치 | 1.1 진행 중인 문서 상태 |
| display/names.ts:127 | 대기 (pending) | 결재 대기 (확인 필요: 공통 사전이라 대상마다 뜻이 다를 수 있음) | 용어 불일치 | 1.1 결재 순서에서 지금 차례 |
| display/names.ts:141, inbox/labels.ts:25 | 해지 | 해제 | 용어 불일치 | 1.1 대결 해제("해지"는 계약 용어) |
| pages/AppShell.tsx:18, inbox/InboxPage.tsx:116 | 승인함 | 결재 | 용어 불일치 | 1.1 결재 화면(메뉴), 2.2 메뉴는 명사 |
| pages/AppShell.tsx:20 | 에이전트 (메뉴) | AI 에이전트 | 용어 불일치 | 1.2 부서별 AI(목록·설정) |
| pages/DesignPage.tsx:29, pages/DesignPage.tsx:33, pages/DesignPage.tsx:66 | 실행 (견본 버튼) | 회의실 예약 | 용어 불일치 | 1.2 카드의 실행 버튼 (디자인 부품 화면 `/design`) |
| pages/DesignPage.tsx:53 | 미리보기 카드 | 실행 전 확인 카드 | 직역투 | 1.2 실행 전 확인, 2.4 (디자인 부품 화면) |
| pages/DesignPage.tsx:64 | 만료 14:32 | 14:32까지 확인 | 용어 불일치 | 1.2 확인 카드의 남은 시간 (디자인 부품 화면) |
| inbox/DelegatePicker.tsx:26 | 서버에 연결하지 못했습니다. | 서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요. | 어색함 | 2.3 오류는 할 일까지(다른 화면의 같은 오류와 맞춤) |
| inbox/DelegatePicker.tsx:39 | 대리인 | 대결자 | 용어 불일치 | 1.1 대결을 맡는 사람 |
| inbox/DelegatePicker.tsx:48 | 이름으로 찾기 (입력칸 라벨) | 이름 검색 | 용어 불일치 | 1.3 찾기(입력칸은 검색) |
| inbox/DelegationPanel.tsx:41, inbox/DelegationPanel.tsx:53 | 위임 목록을 불러오지 못했습니다. | 대결 목록을 불러오지 못했습니다. | 용어 불일치 | 1.1 대결 |
| inbox/DelegationPanel.tsx:92 | 미리보기를 만들지 못했습니다. / 위임을 등록하지 못했습니다. | 대결 내용을 확인하지 못했습니다.(확인 필요) / 대결을 지정하지 못했습니다. | 용어 불일치 | 1.1 대결 지정, 2.4 영어 단어 그대로 |
| inbox/DelegationPanel.tsx:122 | 위임을 해지하지 못했습니다. | 대결을 해제하지 못했습니다. | 용어 불일치 | 1.1 대결 해제 |
| inbox/DelegationPanel.tsx:145 | 등록한 위임이 없습니다. | 지정한 대결이 없습니다. | 용어 불일치 | 1.1 대결, 2.3 빈 상태 |
| inbox/DelegationPanel.tsx:168 | {이름}에게 맡긴 위임 해지 (aria-label) | {이름} 대결 해제 | 용어 불일치 | 1.1 대결 해제 |
| inbox/DelegationPanel.tsx:176 | 새 위임 | 대결 지정 | 용어 불일치 | 1.1 대결 지정 |
| inbox/DelegationPanel.tsx:190 | 금액 한도(원, 비우면 없음) | 라벨 "금액 한도(원)", 칸 아래 작게 "비우면 한도 없음" | 어색함 | 2.4 불필요한 괄호 |
| inbox/DelegationPanel.tsx:200 | 미리보기 (버튼) | 내용 확인 (확인 필요) | 직역투 | 2.4 영어 단어 그대로, 1.2 |
| inbox/DelegationPanel.tsx:207, inbox/DelegationPanel.tsx:208 | 위임 미리보기 (aria-label) / 미리보기 (카드 머리) | 대결 지정 확인 | 직역투 | 1.1 대결, 2.4 영어 단어 그대로 |
| inbox/DelegationPanel.tsx:221 | 등록 | 대결 지정 | 용어 불일치 | 1.1 대결 지정, 2.2 버튼은 동작 이름 |
| inbox/DelegationPanel.tsx:256 | 해지 | 대결 해제 | 용어 불일치 | 1.1 대결 해제, 2.2 위험 동작은 동작 이름 그대로 |
| inbox/DocDetail.tsx:108, inbox/InboxPage.tsx:157 | 요청자 | 기안자 (확인 필요: 용어집에 사람 이름은 없음) | 용어 불일치 | 1.1 기안 |
| inbox/DocDetail.tsx:118, inbox/InboxPage.tsx:161 | 상신 (날짜 칸 이름) | 상신일 (확인 필요) | 어색함 | 1.1 상신은 동작 이름 |
| inbox/DocDetail.tsx:156 | 위임은 {일시}까지입니다. | 대결 기간은 {일시}까지입니다. | 용어 불일치 | 1.1 "위임"은 쓰지 않음 |
| inbox/DocDetail.tsx:162 | 의견(선택, 200자) | 의견 (칸 아래 작게 "선택 · 200자까지"), 반려할 때는 반려 사유 | 용어 불일치 | 1.1 의견, 2.4 "(선택)"은 라벨 옆 작게 |
| inbox/labels.ts:37-43 (쓰는 곳 inbox/DocDetail.tsx:119, inbox/DocDetail.tsx:146, inbox/DocDetail.tsx:156) | 11. 21. 12:44 (다른 해면 2025. 11. 21. 12:44) | 2026년 11월 21일 12:44 | 어색함 | 2.3 날짜(상세) |
| inbox/InboxPage.tsx:179 | 11. 21. 12:44 (목록의 상신 칸) | 오늘 12:44 · 어제 · 11월 20일 (display/format.ts의 formatWhen) | 어색함 | 2.3 날짜(목록) |
| inbox/InboxPage.tsx:150 | 이 함에는 결재 문서가 없습니다. | 함마다 따로: 결재할 문서가 없습니다.(결재 대기) 등 | 어색함 | 2.3 빈 상태 |
| inbox/FormScope.tsx:42 | 양식을 하나 이상 고릅니다. | 양식을 하나 이상 고르세요. | 어색함 | 2.1 할 일은 "~하세요" |
| inbox/labels.ts:14 | 대기 (결재선 단계) | 예정 | 용어 불일치 | 1.1 결재선에서 아직 안 온 차례 |
| inbox/labels.ts:15 | 결재 차례 | 결재 대기 | 용어 불일치 | 1.1 결재 순서에서 지금 차례 |
| inbox/labels.ts:29, inbox/labels.ts:30, inbox/labels.ts:31, inbox/labels.ts:32 | 내 차례 / 대결 / 처리함 / 올린 것 | 결재 대기 / 대결 대기 / 결재 완료 / 기안함 | 용어 불일치 | 1.1 결재 함 이름들 |
| org/AgentRegistryPage.tsx:26, org/OrgPage.tsx:43, org/OrgPage.tsx:44 | 에이전트 등록부를 불러오지 못했습니다. | AI 에이전트 목록을 불러오지 못했습니다. | 용어 불일치 | 1.2 부서별 AI(목록·설정) |
| org/AgentRegistryPage.tsx:45 | 에이전트 등록부 | AI 에이전트 | 용어 불일치 | 1.2 부서별 AI(목록·설정) |
| org/AgentRegistryPage.tsx:46 | 부서 에이전트마다 쓸 수 있는 도구와 위험 등급별 실행 방식, 모델 정책입니다. | AI 에이전트마다 쓸 수 있는 도구와 위험 등급별 실행 방식, 모델 정책입니다. | 용어 불일치 | 1.2 부서별 AI |
| org/AgentRegistryPage.tsx:51, org/AgentRegistryPage.tsx:80, org/OrgPage.tsx:214, org/OrgPage.tsx:219 | 등록된 에이전트가 없습니다. / 기본 에이전트 / 담당 에이전트 / 이 부서가 맡은 에이전트가 없습니다. | "에이전트"를 "AI 에이전트"로 | 용어 불일치 | 1.2 부서별 AI(목록·설정) |
| org/AgentRegistryPage.tsx:79 | 외부 모델 허용 | 외부 AI 사용 | 용어 불일치 | 1.2 외부 AI 모델(직원 화면. `/agents`는 모든 직원 메뉴) |
| org/AgentRegistryPage.tsx:143 | 라우팅 낱말: | 확인 필요(직원 화면이면 숨기거나 "자동 선택 낱말") | 직역투 | 1.2 방식 이름은 관리 화면에만, 2.4 영어 단어 그대로 |
| org/labels.ts:12 | 실행 뒤 되돌리기 안내 | 바로 실행 · 실행 취소 가능 | 직역투 | 1.2 실행 취소, 2.4 |
| org/labels.ts:18 | 인자 조건이 맞을 때 | 확인 필요(예: 값 조건이 맞을 때) | 직역투 | 2.4 직역투(argument). 인자 이름이 없을 때만 나오는 문구 |
| admin/AdminPage.tsx:42 | 시작 날짜가 끝 날짜보다 늦거나 비었습니다. | 시작 날짜가 비었거나 끝 날짜보다 늦습니다. 날짜를 다시 고르세요. | 어색함 | 2.3 오류는 무슨 일 + 할 일 |
| admin/AdminPage.tsx:59 | 관리자 콘솔 | 관리 | 용어 불일치 | 1 머리말(같은 개념은 같은 말: 메뉴 이름 "관리"), 2.4 영어 단어 |
| admin/AdminPage.tsx:91 | {기간}을 보고 있습니다. | 보는 기간: {기간} | 어색함 | 2.3 안내 문장. 날짜 범위가 "(화)"·"(수)"·"(토)"로 끝나면 "을"이 틀립니다 |
| admin/AuditPanel.tsx:12, admin/AuditPanel.tsx:13, admin/AuditPanel.tsx:14 | erp 쓰기 / erp 되돌리기 / erp 거절 | 쓰기 / 실행 취소 / 거절, 출처(erp)는 별도 칸 | 용어 불일치 | 1.4 감사 이벤트 종류, 1.2 실행 취소 |
| admin/AuditPanel.tsx:20, admin/AuditPanel.tsx:21 | 실행 승인 요청 / 실행 승인 결정 | 실행 전 확인 요청 / 실행 전 확인 결정 | 용어 불일치 | 1.2 실행 전 확인(결재의 "승인"과 겹침) |
| admin/AuditPanel.tsx:97 | 직원 ID | 사번 | 용어 불일치 | 1.4 직원 |
| admin/AuditPanel.tsx:141 | {employeeId} (직원 칸에 사번만) | 이름(사번) | 용어 불일치 | 1.4 직원 |
| admin/MetricsPanel.tsx:21 | 기본 에이전트로 | 기본 에이전트 | 어색함 | 2.5 짧은 이름(조사로 끝남) |
| admin/MetricsPanel.tsx:103, admin/MetricsPanel.tsx:169, admin/MetricsPanel.tsx:191 | 로컬 {n} / 외부 요청을 로컬 모델로 내립니다 / 로컬로 내림 | 사내 {n} / 외부 요청을 사내 모델로 돌립니다 / 사내 모델로 돌림 | 직역투 | 1.2 사내 처리, 2.4 영어 단어 그대로 |
| admin/MetricsPanel.tsx:140 | 입구 라우팅 | 에이전트 자동 선택 (확인 필요) | 어색함 | 1.2 자동 선택 |
| eval/EvalReportPage.tsx:26 | 평가 리포트 | 평가 보고서 | 직역투 | 2.4 영어 단어 그대로(같은 화면은 "평가 보고서") |
| eval/EvalReportPage.tsx:74 | (다시 돌림 {n}) | (다시 시도 {n}회) | 용어 불일치 | 1.3 다시 하기, 2.3 숫자에 단위 |
| eval/EvalReportPage.tsx:107 | 이 보고서에는 요약(summary)이 없어 지표 표를 그리지 않습니다. 저장소의 같은 이름 .md 보고서를 보고, 아래 시나리오별 결과만 확인할 수 있습니다. | 이 보고서에는 요약이 없어 지표 표를 그리지 않습니다. 지표는 저장소의 같은 이름 .md 보고서에서 보세요. | 어색함 | 2.3 안내 문장, 2.4 불필요한 괄호 |
| eval/ScenarioTable.tsx:156 | {n}s | {n}초 | 어색함 | 2.3 숫자는 단위 |
| eval/SetSection.tsx:15 | 장치를 만들며 본 셋, 주 결과 아님 (배지) | 확인 필요(예: 개발용 · 주 결과 아님) | 어색함 | 2.5 배지 2~6자 |
| eval/SetSection.tsx:130, eval/SetSection.tsx:142 | 실행 후 되돌림 | 실행 후 실행 취소 (확인 필요: 지표 뜻) | 직역투 | 1.2 실행 취소 |
| eval/SetSection.tsx:205, eval/SetSection.tsx:209 | 정상 업무를 거의 막지 않았다 | 정상 업무 거의 안 막음 | 어색함 | 2.1 해라체 섞지 않음, 2.5 배지 |
| eval/SetSection.tsx:242, eval/SetSection.tsx:249, eval/SetSection.tsx:255 | 승인 요청 / 불필요한 승인 | 실행 전 확인 요청 / 불필요한 확인 (확인 필요) | 용어 불일치 | 1.2 실행 전 확인(결재의 "승인"과 겹침) |
| eval/labels.ts:9 | 기성 도구 기본 | 확인 필요 | 어색함 | 1.4 평가 조건(첫 등장에 한 줄 설명) |
| eval/labels.ts:22 | 주입 | 프롬프트 주입 (확인 필요) | 어색함 | 1.4 평가 조건·유형 |
| chat/ChatPage.tsx:67, chat/ChatPage.tsx:119, chat/ChatPage.tsx:172, inbox/InboxPage.tsx:32, inbox/InboxPage.tsx:45, inbox/InboxPage.tsx:52, inbox/InboxPage.tsx:54, inbox/DocDetail.tsx:60, org/AgentRegistryPage.tsx:26, org/OrgPage.tsx:38, org/OrgPage.tsx:43, org/OrgPage.tsx:44, org/OrgPage.tsx:58, admin/AuditPanel.tsx:46, admin/AuditPanel.tsx:62, admin/EgressPanel.tsx:14, admin/EgressPanel.tsx:18, admin/MetricsPanel.tsx:38, admin/load.ts:67, eval/EvalReportPage.tsx:19, eval/EvalReportPage.tsx:52, api/client.ts:63 | "○○을 불러오지 못했습니다." / "대화를 시작하지 못했습니다." / "승인하지(반려하지) 못했습니다." / "요청을 처리하지 못했습니다." | 끝에 "잠시 뒤 다시 시도해 주세요."를 붙이거나 다시 시도 버튼을 둠 | 어색함 | 2.3 오류는 무슨 일 + 할 일. 대부분 서버 문제 제목이 없을 때의 대체 문구 |
| display/format.ts:11, display/format.ts:30-33, chat/format.ts:7-19 | 2026. 11. 22. 11:20 (상세·미리보기 값) | 2026년 11월 22일 11:20 | 어색함 | 2.3 날짜(상세) |
| display/format.ts:20-27 | 2026. 9. 30.(수) | 2026년 9월 30일(수) (확인 필요: 날짜만 있는 값은 기준에 없음) | 어색함 | 2.3 날짜(상세) |
| display/format.ts:47, display/format.ts:48 | 어제 11:20 / 다른 해 2025. 11. 20. | 어제 / 2025년 11월 20일 (확인 필요) | 어색함 | 2.3 날짜(목록) |

## 분류별 개수 (표의 줄 수)

| 분류 | 개수 |
|---|---|
| 직역투 | 19 |
| AI 말투 | 2 |
| 용어 불일치 | 55 |
| 어색함 | 30 |
| 합계 | 106 |

## 용어집에 없어 정해야 할 말

- **결재 문서를 올린 사람**: 지금 "요청자"(inbox/DocDetail.tsx:108, inbox/InboxPage.tsx:157). 1.1에 기안·기안함은 있지만 사람 이름은 없습니다. "기안자" 후보.
- **사진 첨부 / 붙이기**: 버튼은 "사진 첨부"(chat/ChatPage.tsx:459), 오류·안내는 "붙일 수 없습니다", "다시 붙여"(chat/attachments.ts:44-61, chat/ChatPage.tsx:154, chat/ChatPage.tsx:392). 한 말로 정해야 합니다.
- **에이전트를 부름**: "부를 수 없음"(org/AgentRegistryPage.tsx:81), "부를 수 있는 사람"(:92), "부를 수 없는 에이전트"(admin/MetricsPanel.tsx:9). 호출·사용 가운데 무엇으로 쓸지.
- **도구**: 에이전트가 쓰는 기능의 묶음 이름. "도구 {n}개"(org/AgentRegistryPage.tsx:133), "도구 실행"·"도구 차단"(admin/AuditPanel.tsx:18-19). 1.2는 직원 화면에서 숨긴다는 것만 정했고, 목록 화면에서 부를 이름은 없습니다.
- **바뀌는 값의 종류(create/update/delete)**: "새로 만듦 / 바꿈 / 지움"(chat/format.ts:37, display/preview.ts:24). 추가·변경·삭제 등으로 정할지.
- **위임 토큰**: 에이전트가 직원 대신 일할 때 쓰는 권한(admin/AuditPanel.tsx:16, admin/AuditPanel.tsx:142). 1.1의 "대결"과 다른 개념이라 "위임" 금지 규칙과 따로 이름이 필요합니다.
- **막힘을 나타내는 말(관리·평가 화면)**: 거절(admin/AuditPanel.tsx:14, :25, :31, admin/MetricsPanel.tsx:12)·차단(admin/MetricsPanel.tsx:56, :82)·금지(org/labels.ts:14)·막음(eval/labels.ts:28)이 섞여 있습니다. 1.2의 관리 화면 "정책 차단"과 권한 거절을 구별할지.
- **대결 상태**: 유효·만료·예정·해지(inbox/labels.ts:22-25). 1.1은 "대결 해제"만 정했습니다. "유효"를 "진행 중"이나 "대결 중"으로 할지.
- **결재선 단계 "건너뜀"**(inbox/labels.ts:18).
- **대결 지정 전 확인 단계 이름**: 지금 "미리보기"(inbox/DelegationPanel.tsx:200, :207, :208). 1.2의 "실행 전 확인"은 채팅 카드용입니다.
- **평가 "셋"(set)**: 확인 셋·개발 셋·정상 셋(eval/labels.ts:14), 라벨 "셋"(eval/EvalReportPage.tsx:69, eval/ScenarioTable.tsx:46). 숫자 "셋"과 헷갈립니다.
- **비용을 모르는 요청**: "비용 모름"(admin/EgressPanel.tsx:69, admin/MetricsPanel.tsx:69, eval/EvalReportPage.tsx:89, eval/SetSection.tsx:318).
- **에이전트 자동 선택이 맞는 부서를 못 찾음**: "맞는 부서 없음"(chat/ChatPage.tsx:16), "기본 에이전트"(org/AgentRegistryPage.tsx:80), "기본 에이전트로"(admin/MetricsPanel.tsx:21).

## 모의 데이터

- `src/mocks/`는 화면 사전으로 쓰이지 않습니다(화면 코드가 가져다 쓰지 않음). 다만 gateway·erp 응답을 흉내 낸 문구가 `dev:mock` 화면에 그대로 나옵니다: mocks/inbox.ts:353 "결재를 위임합니다", mocks/inbox.ts:384 "맡긴 위임을 해지했습니다", mocks/chat.ts:338 "실행 승인", mocks/chat.ts:370 "되돌림:". 실제로 고칠 곳은 gateway·erp 문구입니다.
