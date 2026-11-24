# 재설계 전 사용성 문제의 해결 여부

> 확인한 쪽은 서브에이전트입니다(가상 평가). 재설계 전 평가 1([heuristics.md](heuristics.md))의 문제 40개와 페르소나 관찰 항목을 하나씩 대조했습니다. 비교는 [compare.md](compare.md)입니다.

브라우저·서버를 띄우지 않고 파일만 읽어 확인했습니다.

- 모의 화면: `ux/research/a11y/after/shots/`(web `633573d`), 과업 화면·수치: `ux/research/walkthrough/after/`(web `633573d`)
- 실제 스택 화면: `web/docs/images/stack-*.png`, `approvals-confirm-light.png`. 이 그림들은 `3ed076f`(#629)에서 찍어 그 뒤 커밋(`2b78b3f` erp 필드 순서, `50b473d`, `633573d` 날짜·도구 이름)보다 앞섭니다. 그 뒤 고친 것은 코드로 확인했습니다.
- 코드 줄 번호는 지금 작업 트리 기준입니다. 경로의 `web/src/`는 줄였습니다(예: `chat/parts.tsx:150`).
- 심각도는 heuristics.md 1절(평가 1)의 값입니다. H-I4는 3.4절에서 "사용을 막음"으로 올렸지만 아래 집계는 1절 값으로 셉니다.

## 1. 휴리스틱 평가 1절(40건)

| 번호 | 재설계 전 문제(한 줄) | 지금 | 근거 |
|---|---|---|---|
| H-S1 | 탐색이 글자 링크 여섯 개뿐, 결재 건수 없음 | **해결** | `light-inbox.jpg`(아이콘·구획 사이드바, "결재 3"), `shell/Sidebar.tsx:58-61` |
| H-S2 | 모든 사용자가 로그인하면 채팅으로 감 | **해결** | `pages/LoginPage.tsx:83`(역할별 첫 화면), `shell/pending.ts:52`, results.json A1·A2 "결재로 이동(이미 그 화면)" |
| H-S3 | 테마 전환·명령 팔레트·알림 없음 | **해결** | `light-chat-empty.jpg`(찾기·이동 Ctrl K, 알림 종), `shell/Sidebar.tsx:87-88`(테마 메뉴), `shell/CommandPalette.tsx:10` |
| H-S4 | 페이지 제목 배치가 화면마다 다름 | **해결** | `light-org.jpg`, `light-agents.jpg`, `light-admin-metrics.jpg`(모두 위 툴바 왼쪽 제목, `shell/Toolbar.tsx`). 본문 폭은 에이전트 화면만 가운데 좁은 폭 |
| H-C1 | 대화 목록 제목이 첫 메시지라 구별 안 됨 | **일부** | 제목은 여전히 첫 메시지(`chat/ChatPage.tsx:365`). 둘째 줄에 담당 AI·상태·시각을 붙여 구별(`display/conversation.ts:22-33`, `stack-chat-done.png`) |
| H-C2 | 대화 머리의 에이전트가 첫 메시지 기준으로 고정 | **일부** | 답마다 담당 AI 머리가 붙음(`light-chat-answer.jpg`). 머리는 마지막 route 이벤트를 따름(`chat/thread.ts:101-102`, `chat/ChatPage.tsx:272`). 모의 데이터가 회의실 예약도 인사 담당 AI로 돌려 머리가 바뀌는지는 그림으로 확인 못 함 |
| H-C3 | 라우팅 이유가 긴 문장으로 나옴 | **해결** | "자동 선택" 접힘 안으로 옮김(`chat/ChatPage.tsx:381-386`, `stack-chat-answer.png`) |
| H-C4 | 개발자용 도구 이름이 답 위에 보임 | **해결** | "처리 과정 N단계"로 접고 펼치면 표시 이름(`chat/parts.tsx:327-339`, `light-chat-answer.jpg`) |
| H-C5 | 로컬 모델 답의 마크다운이 별표째 보임(실제) | **해결** | `stack-chat-answer.png`(목록이 글머리표로 그려짐), `chat/markdown.tsx` |
| H-C6 | 빈 대화 안내가 한 문장, 예시·바로가기 없음 | **일부** | 안내 문장에 할 수 있는 일 나열, 입력창 자리표시에 예시 한 줄. 예시 질문 버튼·바로가기는 없음(`light-chat-empty.jpg`) |
| H-C7 | 미리보기 중 입력창 잠김, 이유는 작은 회색 글 | **일부** | 문구가 푸는 방법을 알림("위 확인 카드에서 실행하거나 취소하면 이어서 쓸 수 있습니다"). 표시 방식은 그대로 입력창 위 작은 회색 한 줄(`light-chat-preview.jpg`, `E1-01-preview.jpg`) |
| H-P1 | 경비 미리보기가 API 응답 그대로(영문 키, JSON, steps) | **해결** | `E1-01-preview.jpg`(42,000원, 사용일·가맹점·사업자번호·용도, 결재선 이름), results.json E1 확인 기준 4개 통과. 실제 스택 미리보기는 다시 찍지 않아 코드로 확인(`display/preview.ts:4-6`, fields를 양식 스키마로 펴고 id 등은 "자세히"로) |
| H-P2 | 회수 미리보기가 `approval 바꿈`, `pending → withdrawn` | **해결** | `light-chat-preview.jpg`("결재 회수", "상태 진행 → 회수"), results.json E5 통과 |
| H-P3 | 결재선이 "팀장"이나 `approverId`뿐 | **해결** | `E1-01-preview.jpg`("결재선 서도윤 팀장(인사팀) 결재 대기"). 요약 문장에는 "(결재선: 팀장)"이 남음 |
| H-P4 | 만료가 시각만 있고 남은 시간 없음 | **남음** | "오후 5:01까지 확인"(`light-chat-preview.jpg`), `chat/parts.tsx:150-151`(시각만 씀) |
| H-P5 | 되돌릴 수 있는/없는 실행의 버튼 문구가 둘 다 "실행" | **해결** | 버튼이 일 이름("결재 회수", "경비 정산 상신"), 되돌릴 수 없으면 경고 줄 "실행하면 취소할 수 없습니다."(`light-chat-preview.jpg`, `E1-01-preview.jpg`) |
| H-P6 | 실행한 일 카드에 무엇을 어디서 바꿨는지 없음 | **해결** | "3층 소회의실을 내일 오후 2:00–3:00에 예약했습니다"(`light-chat-answer.jpg`), "결재 문서 보기" 링크(`stack-chat-done.png`) |
| H-I1 | 실제 문서 상세의 필드 이름이 키 그대로, 순서 무작위 | **해결** | 이름: `stack-approvals.png`(사유·종료일·종류·시작일). 순서: 그림은 고치기 전이라 섞여 있고, 뒤 커밋 `2b78b3f`가 양식 순서로 돌려줌(`erp/src/main/java/io/inhouse/erp/approval/ApprovalViews.java:22-33`). 순서는 다시 찍은 그림으로는 확인 못 함 |
| H-I2 | 대결 설정 패널이 승인함 오른쪽에 늘 펼쳐짐 | **해결** | 별도 메뉴·화면 "대결 설정"(`light-inbox.jpg`, `light-inbox-delegation-preview.jpg`) |
| H-I3 | 문서 상세가 목록 아래로 펼쳐짐, 다음 결재로 넘어가기 없음 | **해결** | 목록·상세 나란히(`light-inbox-doc-delegated.jpg`), 결재 뒤 다음 문서를 엶(`inbox/InboxPage.tsx:144`) |
| H-I4 | 승인·반려 확인 단계 없음, 반려 의견 선택 | **해결** | 승인 확인 팝오버(`approvals-confirm-light.png`, results.json A1 "승인 확인" 단계), 의견 없으면 반려 비활성·"반려할 때는 반려 사유를 적어 주세요"(`light-inbox-doc-delegated.jpg`) |
| H-I5 | 날짜 형식이 화면마다 다름(미국식 입력 포함) | **해결** | 모든 화면이 `display/format.ts:20-47` 하나를 씀(커밋 `633573d`). 목록은 "오늘 오후 2:51", 상세는 "2026. 11. 23. 오후 4:51"로 쓰임새에 따라 나뉨(`light-inbox-doc-delegated.jpg`). 문서 필드 값 "11/12~11/13"은 모의 데이터 값 그대로 |
| H-I6 | "처리함"·"올린 것" 이름이 모호하고 건수 없음 | **해결** | 탭 "결재 대기 2 · 대결 대기 1 · 결재 완료 · 기안함"(`light-inbox.jpg`) |
| H-D1 | 위임 미리보기 범위가 `양식 leave`, 머리가 `delegation 새로 만듦` | **일부** | 머리는 "대결 지정 확인"으로 고침. 특정 양식을 고르면 여전히 "양식 leave"(results.json A3 확인 기준 실패, 증거 "양식 leave 금액한도 없음"). "모든 양식"일 때만 한국어(`light-inbox-delegation-preview.jpg`) |
| H-D2 | 시작·끝 입력이 미국식 날짜·12시간제 | **해결** | 한국식 날짜 고르개와 "오전 9시" 시 고르개(`A3-01-preview.jpg`, `components/DatePicker.tsx`) |
| H-D3 | 위임 목록에서 맡긴 것/맡은 것이 화살표로만 구별 | **남음** | 서도윤 화면의 "지정한 대결" 목록에 맡은 건 "윤서진 → 서도윤"이 같이 있음(`light-inbox-delegation-preview.jpg`), `inbox/DelegationPanel.tsx:148,162` |
| H-D4 | "모든 양식"을 꺼야 양식 체크박스가 열림 | **남음** | `inbox/FormScope.tsx:31`(`disabled={all}`), `light-inbox-delegation-preview.jpg`(기본 "모든 양식" 켜짐, 나머지 흐림) |
| H-O1 | 조직도에서 이름으로 사람을 찾을 수 없음 | **해결** | "이름으로 사람 찾기" 검색창(`light-org.jpg`) |
| H-O2 | 에이전트 화면이 도구·역할·문서 범위 코드와 조건식을 그대로 씀 | **해결** | 도구 표시 이름·"역할 직원"(`light-agents.jpg`), 조건 "금액이 1,000,000원보다 클 때"(`org/labels.ts:31-37`), 도구 코드는 감사 권한자에게만(`org/AgentRegistryPage.tsx:83,136-139`), 문서 범위 줄 없음 |
| H-O3 | 에이전트가 한 열 긴 카드 나열이라 견주기 어려움 | **남음** | `light-agents.jpg`(가운데 한 열), `org/AgentRegistryPage.tsx:60` |
| H-A1 | 감사 로그가 `emp-`·`hr`·작업 코드, 필터가 직원 ID | **일부** | 이름·한국어 이름이 앞에 붙었지만 코드가 옆에 남음("윤서진 emp-2002", "인사 hr", "대결 지정 delegation_register")(`light-admin-audit.jpg`, results.json M3 확인 기준 2개 실패). 필터는 여전히 사번(`admin/AuditPanel.tsx:103-104`) |
| H-A2 | 감사 로그 "종류" 칸에 출처 코드가 섞임 | **남음** | "실행 취소 erp", "정책 차단 mcp"(`light-admin-audit.jpg`), `admin/AuditPanel.tsx:144` |
| H-A3 | 외부 전송 기록에 직원·대화가 없음 | **남음** | `light-admin-egress.jpg`, results.json M1 "어느 직원·어느 대화의 요청인지 보인다" 실패 |
| H-A4 | 외부 전송 행이 접기만 있어 무엇을 가렸는지 펼쳐야 보임 | **일부** | 행에 "가림 1곳: 전화번호"처럼 종류가 배지로 보이고 가림 없음은 회색 배지(`light-admin-egress.jpg`). 같은 높이 접기 목록은 그대로 |
| H-A5 | 비용이 달러 소수뿐 | **남음** | "$0.061", "$0.042"(`light-admin-metrics.jpg`), `admin/MetricsPanel.tsx:68`(`formatUsd`) |
| H-A6 | 기간 입력이 미국식 날짜 | **해결** | "2026. 11. 18.(수)" 날짜 고르개(`light-admin-audit.jpg`) |
| H-E1 | 시나리오가 ID로만 보임 | **남음** | `M4-01-scenario.jpg`, `eval/ScenarioTable.tsx:94`(`s.id`), results.json M4 확인 기준 실패 |
| H-E2 | 한 페이지에 표가 많고 길어 결론이 묻힘 | **남음** | 한 페이지에 실행 조건·세트별 표 여럿·시나리오 표가 이어짐(`eval/EvalReportPage.tsx:64-112`, `eval/SetSection.tsx:29,173,242,271,302`). 전체 캡처 높이 4340px(재설계 전 4174px)(`light-eval.jpg`) |
| H-E3 | 기기·커밋·모델 같은 실행 메타가 결과보다 먼저 크게 나옴 | **남음** | "실행 조건"(기기·커밋·모델)이 맨 위(`light-eval.jpg`, `eval/EvalReportPage.tsx:64`). 실행 메모만 접힘 |
| H-L1 | 로그인에 무엇을 하는지·문의처가 없음 | **해결** | 소개 한 줄과 "IT 담당 부서에 문의" 안내(`light-login.jpg`, `pages/LoginPage.tsx:77`) |

## 2. 휴리스틱 평가 3.5절(페르소나 관찰에서만 나온 것, 3건)

| 번호 | 재설계 전 문제(한 줄) | 지금 | 근거 |
|---|---|---|---|
| P-1 | 대리인이 내 차례 문서의 요청자 본인이면 그 문서를 처리할 사람이 없는데 알리지 않음 | **남음** | 대결 지정 확인에 대리인·시작·끝·양식·금액한도만 나옴(`light-inbox-delegation-preview.jpg`). web·erp 대결 코드에 이 경고가 없음(`inbox/DelegationPanel.tsx:210-233`) |
| P-2 | 1920×1080에서 위임 "등록" 버튼이 화면 밖 | **남음** | 확인 시트가 폼 아래 흐름에 붙어 "대결 지정" 버튼이 1080 화면 밖(`A3-01-preview.jpg`), 스크롤 처리 없음(`inbox/DelegationPanel.tsx:210`) |
| P-3 | "인용 확인 안 됨" 표시가 답 문장 쪽에는 없음 | **남음** | 근거 목록에만 "원문 대조 안 됨"(`light-chat-answer.jpg`, `chat/parts.tsx:57-60`), 답 문장에는 표시 없음 |

## 3. baseline.md 3절 "스크립트가 못 보는 망설임"(5건)

| 번호 | 재설계 전 문제(한 줄) | 지금 | 근거 |
|---|---|---|---|
| B-1 | 결재자 첫 화면이 채팅, 대결 문서는 "대결" 탭에만 있어 놓침 | **일부** | 첫 화면은 결재(`pages/LoginPage.tsx:83`, results.json A1·A2). 대결 문서는 여전히 "결재 대기"가 아닌 "대결 대기" 탭에만 있으나 탭 건수 "대결 대기 1"과 사이드바 "결재 3"(합계)이 보임(`light-inbox.jpg`) |
| B-2 | "최근 24시간"이 눌린 채 날짜 칸은 7일 전부터 | **일부** | "보는 기간: 최근 24시간" 줄이 생겼지만 날짜 칸은 여전히 11. 18.~11. 24.(`light-admin-audit.jpg`, `light-admin-egress.jpg`, `admin/AdminPage.tsx:35,85`) |
| B-3 | 회의실 예약을 되돌리면 배지는 "되돌림"인데 문장은 "예약했습니다" | **남음** | "취소됨 · 3층 소회의실을 내일 오후 2:00–3:00에 예약했습니다."(`E2-01-undone.jpg`) |
| B-4 | 대리인이 요청자 본인인 문서를 화면이 알리지 않음(P-1과 같음) | **남음** | P-1과 같음 |
| B-5 | 1080 높이에서 위임 "등록" 버튼이 화면 밖(P-2와 같음) | **남음** | P-2와 같음, `A3-01-preview.jpg` |

## 4. 집계

### 상태별(48행)

| 지금 | 1절(40) | 3.5절(3) | baseline 3절(5) | 합계 |
|---|---|---|---|---|
| 해결 | 23 | 0 | 0 | 23 |
| 일부 | 7 | 0 | 2 | 9 |
| 남음 | 10 | 3 | 3 | 16 |
| 확인 못 함 | 0 | 0 | 0 | 0 |
| 합계 | 40 | 3 | 5 | 48 |

B-4·B-5는 P-1·P-2와 같은 문제라, 겹침을 빼면 46건(해결 23, 일부 9, 남음 14)입니다.

### 재설계 전 심각도별

1절은 1절 표의 심각도로 셉니다. 3.5절 세 건은 문서에 "헷갈림"으로 적혀 있고, baseline 3절 다섯 건은 heuristics.md 3.2·3.5절에서 같은 문제를 "헷갈림"으로 매겨 헷갈림으로 셉니다.

| 심각도 | 해결 | 일부 | 남음 | 확인 못 함 | 합계 |
|---|---|---|---|---|---|
| 사용을 막음 | 1(H-P1) | 0 | 0 | 0 | 1 |
| 헷갈림 | 12 | 7 | 10 | 0 | 29 |
| 다듬기 | 10 | 2 | 6 | 0 | 18 |
| 합계 | 23 | 9 | 16 | 0 | 48 |

- 헷갈림 중 1절(21): 해결 12(S1, S2, C4, P2, P3, P5, I1, I3, I4, D2, O1, O2), 일부 5(C1, C2, C6, D1, A1), 남음 4(D3, A3, E1, E2)
- 헷갈림 중 3.5절·baseline(8): 일부 2(B-1, B-2), 남음 6(P-1~3, B-3~5)
- 다듬기(18): 해결 10(S3, S4, C3, C5, P6, I2, I5, I6, A6, L1), 일부 2(C7, A4), 남음 6(P4, D4, O3, A2, A5, E3)
- 3.4절대로 H-I4를 "사용을 막음"으로 세면 사용을 막음 2건 모두 해결, 헷갈림은 해결이 11건이 됩니다.

## 5. 덧붙임

- 과업 걸어 보기(after)는 성공 7 · 부분 성공 5입니다(재설계 전 4 · 8). 남은 부분 성공 5건(A3, M1, M2, M3, M4)은 위의 H-D1, H-A3, H-A1, H-E1과 운영 지표의 "표 근처 기간"입니다.
- A3(대결 지정) 조작 단계가 10에서 14로 늘었습니다(목표 7 이하). 날짜 고르개로 바뀌어 클릭이 늘었고, "모든 양식" 끄기(H-D4)도 남았습니다.
