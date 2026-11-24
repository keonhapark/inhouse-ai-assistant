# 재설계 뒤 휴리스틱 평가(닐슨 10원칙, 독립 평가)

> 평가자는 사람이 아니라 결론을 모르는 서브에이전트입니다(가상 평가). 재설계 전 독립 평가([heuristics-independent.md](heuristics-independent.md))와 같은 방식이라 개수를 견줄 수 있습니다. 비교는 [compare.md](compare.md)입니다.

재설계 뒤 웹 화면을 닐슨 10원칙으로 평가한 결과입니다. 재설계 전 평가(`ux/research/heuristics*.md`)는 읽지 않고 따로 평가했습니다. 브라우저·서버는 띄우지 않았고, 찍어 둔 그림과 코드만 읽었습니다.

## 평가 방법

- **평가자:** 1명(이 세션). 그림을 보고 판단했고, 화면을 직접 조작하지는 않았습니다.
- **본 것**
  - [모의] 모의 데이터 화면, web `633573d`: `ux/research/a11y/after/shots/`(밝음 14장 전부, 어두움 4장: chat-preview, inbox-doc-delegated, org, admin-audit), `ux/research/walkthrough/after/shots/`(17장 중 15장)
  - [실제] 실제 스택 화면: `web/docs/images/stack-*.png` 8장(커밋 `3ed076f`, 11-24 16:17). 같은 시각에 찍은 문서용 모의 그림 `approvals-confirm-light.png`, `ops-eval-light.png`도 참고했습니다.
  - [코드] 그림만으로 판단이 안 될 때 `web/src/`와 erp 코드를 확인했습니다.
- **실제 그림의 시점:** `stack-*.png`는 #634·#636·#638보다 먼저 찍혔습니다. 그 뒤 커밋에서 고친 것(결재 문서 필드 순서, AI 에이전트 화면의 도구 코드 이름, 메뉴 "평가 리포트")은 세지 않았습니다. 실제 그림에만 보이는 문제는 지금 코드에서도 남아 있는지 확인한 것만 셌습니다.
- **세는 기준:** 그림에서 직접 본 것만 셉니다. 원칙은 가장 가까운 하나만 붙입니다. 여러 화면에 같은 컴포넌트로 나타나는 문제는 처음 나온 화면에서 한 번만 셉니다(예: 운영 화면의 기간 표시).
- **심각도**
  - **사용을 막음:** 과업을 못 끝내거나, 잘못된 결재·실행으로 이어질 수 있음
  - **헷갈림:** 끝낼 수는 있지만 잘못 읽거나 멈칫하게 함
  - **다듬기:** 일관성·문구·모양 문제로, 과업 결과에는 영향이 작음
- 근거 경로는 줄여 적었습니다. `a11y/…`, `walkthrough/…`는 `ux/research/` 아래, `images/…`는 `web/docs/images/` 아래, `web/src/…`와 `erp/…`는 저장소 루트 기준입니다.

## 1. 로그인

| 번호 | 문제 | 원칙 | 심각도 | 근거 |
|---|---|---|---|---|
| L-1 | 오류 문구 "사번 또는 비밀번호가 맞지 않습니다."에 다음에 할 일이 없습니다. 할 일은 카드 맨 아래 상시 안내에만 있습니다. | N9 | 다듬기 | [모의] a11y/after/shots/light-login-error.jpg |
| L-2 | 도움말이 "IT 담당 부서에 문의"라고만 해서, 어느 팀(IT운영팀)이나 어떤 연락처인지 알 수 없습니다. | N10 | 다듬기 | [모의] a11y/after/shots/light-login.jpg |
| L-3 | 비밀번호 보기 단추가 없습니다. 틀린 입력을 보내기 전에 확인할 방법이 없습니다. | N5 | 다듬기 | [모의] a11y/after/shots/light-login-error.jpg |
| L-4 | 사번 칸에 형식 예시(E1001처럼)가 없습니다. 감사 로그 사번 칸에는 "예: E0007"이 있어서 화면마다 다릅니다. | N6 | 다듬기 | [모의] a11y/after/shots/light-login.jpg, light-admin-audit.jpg |

## 2. 셸·탐색

| 번호 | 문제 | 원칙 | 심각도 | 근거 |
|---|---|---|---|---|
| S-1 | 탐색 막대의 결재 건수 "3"은 결재 대기 2건과 대결 대기 1건을 합친 수입니다. 들어가면 "결재 대기 2"가 먼저 보여서 두 숫자가 맞지 않아 보입니다. | N4 | 다듬기 | [모의] a11y/after/shots/light-inbox.jpg |
| S-2 | 아래 끝 사용자 이름·팀에 메뉴라는 표시(꺾쇠 등)가 없습니다. 테마와 로그아웃이 어디 있는지 찾기 어렵습니다. | N6 | 다듬기 | [모의] a11y/after/shots/light-chat-empty.jpg |
| S-3 | 알림 종에 빨간 점만 있고 건수나 무슨 알림인지는 없습니다. | N1 | 다듬기 | [모의] a11y/after/shots/light-inbox.jpg |

## 3. 채팅(AI 비서)

| 번호 | 문제 | 원칙 | 심각도 | 근거 |
|---|---|---|---|---|
| C-1 | 답이 오는 동안 대화 목록이 그대로입니다. 새 대화는 목록에 없고 "아직 대화가 없습니다"가 남으며, 확인을 끝낸 대화에도 "확인 필요" 점이 남습니다. 목록은 응답이 끝나야 새로 고칩니다. | N1 | 다듬기 | [모의] walkthrough/after/shots/E3-01-citations.jpg, E2-01-undone.jpg, E1-02-done.jpg, E5-02-done.jpg / [코드] web/src/chat/ChatPage.tsx `finishStream`에서만 `refreshList` |
| C-2 | 빈 화면 입력창에 있던 "자동 선택 ▾" 칩이 첫 메시지 뒤에는 사라집니다. 담당 AI를 바꾸려면 새 대화를 열어야 한다는 안내도 없습니다. | N3 | 다듬기 | [모의] a11y/after/shots/light-chat-empty.jpg, light-chat-answer.jpg |
| C-3 | 빈 화면에서 무엇을 시킬 수 있는지는 회색 문장 한 줄뿐이고, 눌러서 시작할 예시는 없습니다. 같은 뜻의 문장이 목록과 본문에 두 번 나옵니다. | N6 | 다듬기 | [모의] a11y/after/shots/light-chat-empty.jpg |
| C-4 | "처리 과정 1단계/2단계" 접기에 무엇이 들어 있는지 이름으로는 알 수 없습니다. | N2 | 다듬기 | [모의] a11y/after/shots/light-chat-answer.jpg |
| C-5 | 실제 답에서 숫자와 단위가 띄어져 나옵니다("1 년에 총 12 일", "11 월 26 일"). | N4 | 다듬기 | [실제] images/stack-chat-answer.png, stack-chat-done.png |

## 4. 실행 전 확인·완료한 일

| 번호 | 문제 | 원칙 | 심각도 | 근거 |
|---|---|---|---|---|
| P-1 | 결재 회수 카드의 바뀌는 값이 "상태 진행 → 회수"입니다. 용어집의 "진행 중"이 아니고, 화살표 기호를 씁니다. | N4 | 다듬기 | [모의] a11y/after/shots/light-chat-preview.jpg |
| P-2 | 경비 정산 카드 설명 "경비 정산 결재를 올립니다(결재선: 팀장)."이 바로 아래 결재선 줄("서도윤 팀장(인사팀) 결재 대기")과 겹칩니다. | N8 | 다듬기 | [모의] walkthrough/after/shots/E1-01-preview.jpg |
| P-3 | "완료" 표시 옆 요약이 "휴가 신청 결재를 올립니다(결재선 1단계)"처럼 앞으로 할 일의 말투입니다. 이미 올렸는지 읽어서는 확신하기 어렵습니다. | N1 | 헷갈림 | [실제] images/stack-chat-done.png |
| P-4 | 실제 답에 내부 ID가 그대로 나옵니다: "결재 번호는 doc_d0459b3d4d4c 입니다", "(행동 act_ee77abcc42de)". 옛 용어 "되돌릴 수 있습니다"도 함께 나옵니다. | N2 | 헷갈림 | [실제] images/stack-chat-done.png |
| P-5 | 실행 취소 뒤 "취소됨" 행의 문장이 "3층 소회의실을 내일 오후 2:00–3:00에 예약했습니다."로 그대로 남아, 예약이 살아 있는 것처럼 읽힙니다. | N1 | 헷갈림 | [모의] walkthrough/after/shots/E2-01-undone.jpg |

## 5. 결재·문서 상세

| 번호 | 문제 | 원칙 | 심각도 | 근거 |
|---|---|---|---|---|
| D-1 | 결재선에서 아직 차례가 오지 않은 사람에 "대기"를 붙여, 바로 앞 단계의 "결재 대기"와 거의 같은 말로 보입니다. 용어집이 이 혼동 때문에 "예정"으로 정한 말입니다. | N4 | 헷갈림 | [모의] a11y/after/shots/light-inbox-doc-delegated.jpg / [코드] web/src/inbox/labels.ts:17 `waiting: '대기'` |
| D-2 | 기안함에서 내 문서를 열어도 회수 단추가 없습니다. 잘못 올린 결재는 채팅에서 말로 시켜야만 회수할 수 있습니다. | N3 | 헷갈림 | [모의] walkthrough/after/shots/E4-01-doc.jpg / [코드] web/src/inbox/DocDetail.tsx(동작은 결재 대기·대결 대기 칸에서만) |
| D-3 | 한 화면에 날짜 표기가 넷입니다: 제목 "11/27~11/28", 값 "2026. 11. 27.(금)", 상신 "2026. 11. 24. 오후 2:50", 목록 "오늘 오후 2:50". 값 행도 "11/12~11/13"입니다. | N4 | 다듬기 | [모의] walkthrough/after/shots/A1-01-doc.jpg, a11y/after/shots/light-inbox-doc-delegated.jpg |
| D-4 | 승인 뒤 상세가 "왼쪽 목록에서 문서를 고르세요."로 비고, 남은 결재 대기 문서(2건)로 넘어가지 않습니다. 처음 들어갔을 때도 첫 문서가 열려 있지 않습니다. | N7 | 다듬기 | [모의] walkthrough/after/shots/A2-02-done.jpg, a11y/after/shots/light-inbox.jpg |
| D-5 | 승인 결과 "11월 출장 경비 정산을 승인했습니다."가 바로 아래 빈 상태 문장("대신 결재할 문서가 없습니다.")과 같은 회색 글자여서 결과 알림으로 눈에 띄지 않습니다. | N1 | 다듬기 | [모의] walkthrough/after/shots/A2-02-done.jpg |
| D-6 | 의견 칸은 자리 표시 글 "의견"이 라벨을 대신하고, 글자 수 제한이 보이지 않습니다. | N6 | 다듬기 | [모의] a11y/after/shots/light-inbox-doc-delegated.jpg |
| D-7 | 실제 상세 머리에 내부 ID "doc_d0459b3d4d4c"가 문서 번호처럼 나옵니다. | N2 | 다듬기 | [실제] images/stack-approvals.png |
| D-8 | 밝은 테마에서 주 버튼 "승인"의 파스텔 면이 옆의 비활성 "반려"와 무게 차이가 작습니다. 눌러도 되는 상태인지 한눈에 읽기 어렵습니다. | N1 | 다듬기 | [모의] a11y/after/shots/light-inbox-doc-delegated.jpg (어두움 dark-inbox-doc-delegated.jpg는 차이가 분명함) |

## 6. 대결 설정

| 번호 | 문제 | 원칙 | 심각도 | 근거 |
|---|---|---|---|---|
| G-1 | 새 대결 지정의 기본값이 "모든 양식" 체크 + 금액 한도 비움(=한도 없음)입니다. "모든 양식"이 체크된 동안 개별 양식 체크 상자는 비활성이라, 휴가만 맡기려면 먼저 "모든 양식"을 풀어야 합니다. 확인 카드도 "양식 모든 양식 / 금액한도 없음"만 보여 주고, 용어집의 "범위가 넓은 대결" 경고가 없습니다. 기본값 그대로 지정하면 의도보다 넓은 대결 권한이 넘어갑니다. | N5 | 사용을 막음 | [모의] a11y/after/shots/light-inbox-delegation-preview.jpg, walkthrough/after/shots/A3-02-done.jpg / [실제] images/stack-delegations.png / [코드] web/src/inbox/FormScope.tsx(`disabled={all}`) |
| G-2 | "지정한 대결" 목록에 내가 맡긴 대결과 내가 맡은 대결이 섞여 있습니다. 방향은 "윤서진 → 서도윤"의 화살표로만 알 수 있습니다. 내가 대결자인 대결도 "지정한 대결"로 불립니다. | N2 | 헷갈림 | [모의] walkthrough/after/shots/A3-02-done.jpg / [코드] web/src/inbox/DelegationPanel.tsx(`role: 'all'`, 제목 "지정한 대결") |
| G-3 | 확인 카드 라벨이 "대리인", "금액한도"입니다. 바로 위 입력 폼은 "대결자", "금액 한도(원)"이어서 같은 흐름에서 말이 바뀝니다. | N4 | 다듬기 | [모의] a11y/after/shots/light-inbox-delegation-preview.jpg / [코드] web/src/mocks/inbox.ts:369-373(모의 서버 문구) |
| G-4 | 지정한 뒤 안내가 "한지우를 대결자로 지정합니다."로 현재형이고, 폼 맨 아래 "내용 확인" 단추 밑에 나옵니다. 끝났는지, 위 목록에 새로 생긴 줄이 그 결과인지 이어서 읽기 어렵습니다. | N1 | 헷갈림 | [모의] walkthrough/after/shots/A3-02-done.jpg / [코드] erp/src/main/java/io/inhouse/erp/delegation/DelegationService.java:114(실제 erp도 "지정합니다") |
| G-5 | 대결자를 고르면 같은 이름이 세 번 보입니다(고른 사람, 검색어, 라디오). 지정한 뒤에는 검색어 "한지우"가 남은 채 "아직 고르지 않았습니다."가 나옵니다. | N8 | 다듬기 | [모의] a11y/after/shots/light-inbox-delegation-preview.jpg, walkthrough/after/shots/A3-02-done.jpg |
| G-6 | 확인 카드가 폼 아래에 붙어 나와서, 1920×1080에서 "대결 지정" 단추가 첫 화면 밖에 있습니다. | N1 | 다듬기 | [모의] walkthrough/after/shots/A3-01-preview.jpg |

## 7. 조직도

| 번호 | 문제 | 원칙 | 심각도 | 근거 |
|---|---|---|---|---|
| O-1 | 왼쪽 트리와 오른쪽 "하위 부서" 목록이 같은 부서를 두 번 보여 줍니다. 구성원 행에도 "부서장" 태그와 직책 "대표이사"가 함께 있습니다. | N8 | 다듬기 | [모의] a11y/after/shots/light-org.jpg / [실제] images/stack-org.png |

## 8. AI 에이전트

| 번호 | 문제 | 원칙 | 심각도 | 근거 |
|---|---|---|---|---|
| A-1 | 한 화면에 같은 대상을 부르는 이름이 넷입니다: 메뉴 "AI 에이전트", 안내 "담당 AI", 제목 "전사 비서", 설명 "부서 에이전트". | N4 | 헷갈림 | [모의] a11y/after/shots/light-agents.jpg / [실제] images/stack-agents.png |
| A-2 | 직원 화면에 설정 정보가 그대로 나옵니다: "v0.1.0 · 1단계", 라우팅 낱말 "맡는 말: 회의실, 예약, … 어디, 누구", "사용할 수 있는 사람: 역할 직원". | N2 | 다듬기 | [모의] a11y/after/shots/light-agents.jpg |
| A-3 | 에이전트 여럿이 한 페이지에 길게 이어지고, 목차나 바로 가기가 없습니다. | N7 | 다듬기 | [실제] images/stack-agents.png(아래에 "인사 담당 AI"가 이어짐) |

## 9. 운영 화면(운영 지표·외부 전송 기록·감사 로그)

탐색 막대의 운영 묶음은 네 화면이고, 평가 보고서는 10절에서 따로 셉니다.

### 운영 지표

| 번호 | 문제 | 원칙 | 심각도 | 근거 |
|---|---|---|---|---|
| M-1 | "최근 24시간"을 골라도 시작·끝 날짜 칸에는 "2026. 11. 18.(수) ~ 2026. 11. 24.(화)"(7일)가 남아 있습니다. 바로 아래 "보는 기간: 최근 24시간"과 모순됩니다. 운영 세 화면이 모두 같습니다(여기서 한 번만 셈). | N1 | 헷갈림 | [모의] a11y/after/shots/light-admin-metrics.jpg, light-admin-egress.jpg, light-admin-audit.jpg / [실제] images/stack-ops-metrics.png / [코드] web/src/admin/AdminPage.tsx:37-38(날짜 칸 기본값이 미리 정한 기간과 따로 움직임) |
| M-2 | 합계 카드 "정책 차단 9" 아래 "차단 이유"에도 "정책 차단 4건"이 한 항목으로 있습니다. 합계와 항목이 같은 이름입니다. | N4 | 헷갈림 | [모의] a11y/after/shots/light-admin-metrics.jpg, walkthrough/after/shots/M2-01-metrics.jpg |
| M-3 | 합계 카드 숫자에 단위가 없습니다("에이전트 실행 134", "정책 차단 9"). 옆 카드는 "96 / 255건"처럼 단위를 붙입니다. | N4 | 다듬기 | [모의] a11y/after/shots/light-admin-metrics.jpg |
| M-4 | 빈 상태 문구 "이 기간에 막은 요청이 없습니다."가 화면의 "정책 차단"과 다른 말을 씁니다. | N4 | 다듬기 | [실제] images/stack-ops-metrics.png / [코드] web/src/admin/MetricsPanel.tsx:119 |

### 외부 전송 기록

| 번호 | 문제 | 원칙 | 심각도 | 근거 |
|---|---|---|---|---|
| X-1 | 기록을 펼쳐도 어느 직원·어느 대화의 요청인지 나오지 않습니다. 누가 보냈는지 설명하려면 시각을 외워 감사 로그에서 다시 찾아야 합니다. | N6 | 헷갈림 | [모의] walkthrough/after/shots/M1-01-egress.jpg / [코드] web/src/admin/EgressPanel.tsx(직원·대화 칸 없음) |
| X-2 | 펼친 본문의 역할 이름이 영문 고정폭 "system", "user"입니다. | N2 | 다듬기 | [모의] walkthrough/after/shots/M1-01-egress.jpg |

### 감사 로그

| 번호 | 문제 | 원칙 | 심각도 | 근거 |
|---|---|---|---|---|
| U-1 | 오래된 것부터 늘어서고 "20건 (더 있음)"이라, 가장 최근 사건은 "더 보기" 뒤에 있습니다. 외부 전송 기록은 최신순이어서 두 운영 화면의 순서가 반대입니다. | N4 | 헷갈림 | [모의] a11y/after/shots/light-admin-audit.jpg, light-admin-egress.jpg / [실제] images/stack-ops-audit.png |
| U-2 | 정책 차단된 행에도 도구 속성 태그 "실행 취소 가능"이 붙어서 결과와 섞여 읽힙니다. "실행 취소" 행에도 "실행 취소 가능"이 붙어 있습니다. | N8 | 다듬기 | [모의] walkthrough/after/shots/M3-01-audit.jpg, a11y/after/shots/light-admin-audit.jpg |
| U-3 | 차단 사유가 "문서에서 온 지시로는 대결 등록을 부를 수 없습니다"입니다. 화면의 다른 곳에서 쓰는 "대결 지정", "사용"과 말이 다릅니다. | N4 | 다듬기 | [모의] walkthrough/after/shots/M3-01-audit.jpg |
| U-4 | 실제 로그는 "LLM 요청 gateway · 시스템 · – · –" 같은 행 9개가 목록 대부분을 차지합니다. 묶거나 숨길 수 없습니다. | N8 | 다듬기 | [실제] images/stack-ops-audit.png |
| U-5 | 작업 칸에 코드 이름 "login"이 그대로 나옵니다(표시 이름 없음). | N2 | 다듬기 | [실제] images/stack-ops-audit.png / [코드] web/src/display/names.ts에 login 대응 없음 |
| U-6 | 기간 세그먼트는 누르면 바로 적용되는데, 종류·에이전트·사번 필터는 "적용"을 눌러야 합니다. | N4 | 다듬기 | [모의] a11y/after/shots/light-admin-audit.jpg |
| U-7 | 직원 칸의 모든 행에 "대행 토큰"이 반복되어 이름 읽기를 방해합니다. | N8 | 다듬기 | [모의] a11y/after/shots/light-admin-audit.jpg |
| U-8 | 직원은 사번으로만 거를 수 있고 이름으로는 찾을 수 없습니다. | N7 | 다듬기 | [모의] a11y/after/shots/light-admin-audit.jpg |

## 10. 평가 보고서

| 번호 | 문제 | 원칙 | 심각도 | 근거 |
|---|---|---|---|---|
| V-1 | 시나리오 이름이 코드 ID("normal-room-reserve-weekly")뿐입니다. | N2 | 헷갈림 | [모의] walkthrough/after/shots/M4-01-scenario.jpg / [코드] web/src/eval/ScenarioTable.tsx:94 |
| V-2 | 기대와 다른 이유가 단언 원문입니다: "dbAssertions[0] $.items[?(@.status=='confirmed')] count_equals 1: 찾은 것 0개". 무엇이 왜 틀렸는지 한 줄로 읽히지 않습니다. | N9 | 헷갈림 | [모의] walkthrough/after/shots/M4-01-scenario.jpg |
| V-3 | 1280 폭에서 표 오른쪽 "이 프로젝트" 열이 잘려 보이고("25/40 (62.5%, 45…"), 가로로 넘길 수 있다는 표시가 없습니다. | N6 | 다듬기 | [모의] a11y/after/shots/light-eval.jpg |
| V-4 | 보고서 고르개는 "정상 셋", 본문 제목은 "정상 세트"입니다. | N4 | 다듬기 | [모의] a11y/after/shots/light-eval.jpg |
| V-5 | 조건 이름(장치 없음·쓰기 차단·이 프로젝트)에 설명이 없고, "18/40 (45.0%, 29.3%~61.5%)"의 구간이 무엇인지(신뢰 구간 등) 적혀 있지 않습니다. | N10 | 헷갈림 | [모의] a11y/after/shots/light-eval.jpg |
| V-6 | 실행 조건 블록에서 기기 문자열("macOS-26.5-arm64-arm-64bit arm64"), 커밋, 설정 파일 경로가 세트·조건과 같은 무게로 놓여 있습니다. | N8 | 다듬기 | [모의] a11y/after/shots/light-eval.jpg |
| V-7 | 범례 문장에 영문이 섞여 있습니다: "기대(시나리오 expect)", "경로 external · 넘긴 에이전트 assistant(기대 assistant)". | N2 | 다듬기 | [모의] walkthrough/after/shots/M4-01-scenario.jpg |

## 11. 집계

### 원칙 × 심각도

| 원칙 | 사용을 막음 | 헷갈림 | 다듬기 | 합계 |
|---|---|---|---|---|
| N1 시스템 상태 보이기 | 0 | 4 | 5 | 9 |
| N2 실제 세계와 맞추기 | 0 | 3 | 6 | 9 |
| N3 사용자 통제와 자유 | 0 | 1 | 1 | 2 |
| N4 일관성과 표준 | 0 | 4 | 10 | 14 |
| N5 오류 예방 | 1 | 0 | 1 | 2 |
| N6 기억보다 알아보기 | 0 | 1 | 5 | 6 |
| N7 유연성과 효율 | 0 | 0 | 3 | 3 |
| N8 미적·최소 디자인 | 0 | 0 | 7 | 7 |
| N9 오류 알아보기·고치기 | 0 | 1 | 1 | 2 |
| N10 도움말과 문서 | 0 | 1 | 1 | 2 |
| **합계** | **1** | **15** | **40** | **56** |

### 화면별

| 화면 | 사용을 막음 | 헷갈림 | 다듬기 | 합계 |
|---|---|---|---|---|
| 로그인 | 0 | 0 | 4 | 4 |
| 셸·탐색 | 0 | 0 | 3 | 3 |
| 채팅 | 0 | 0 | 5 | 5 |
| 실행 전 확인·완료한 일 | 0 | 3 | 2 | 5 |
| 결재·문서 상세 | 0 | 2 | 6 | 8 |
| 대결 설정 | 1 | 2 | 3 | 6 |
| 조직도 | 0 | 0 | 1 | 1 |
| AI 에이전트 | 0 | 1 | 2 | 3 |
| 운영 지표 | 0 | 2 | 2 | 4 |
| 외부 전송 기록 | 0 | 1 | 1 | 2 |
| 감사 로그 | 0 | 1 | 7 | 8 |
| 평가 보고서 | 0 | 3 | 4 | 7 |
| **합계** | **1** | **15** | **40** | **56** |

## 12. 명세(`ux/design-system.md`)·용어집(`ux/copy-guide.md`)과 어긋나는 구현

위 표의 개수와는 따로 적습니다(일부는 위 항목과 겹칩니다).

| 번호 | 어긋남 | 명세·용어집 | 구현 근거 |
|---|---|---|---|
| R-1 | 시각을 12시간제("오늘 오후 4:51", "오후 5:01까지 확인"), 날짜를 "2026. 11. 24."로 표기합니다. 대결 시각 고르개도 "오후 5시"입니다. 재설계 직후 실제 그림(`stack-*.png`)은 "오늘 16:10", "2026년 11월 24일(화)", "17시"로 명세와 맞았는데, #638에서 바뀌었습니다. | copy-guide 2.3(`오늘 12:44`, 상세 `2026년 11월 21일 12:44`), design-system 3.5(24시간제 고르개) | web/src/display/dates.ts `koDate`, `koHour` / [모의] 전 화면 |
| R-2 | 결재선 아직 안 온 차례가 "대기"입니다. | copy-guide 1.1 "예정" | web/src/inbox/labels.ts:17 |
| R-3 | 회수 카드 상태 값이 "진행"입니다. | copy-guide 1.1 "진행 중" | [모의] light-chat-preview.jpg |
| R-4 | 대결 지정 확인 카드 라벨이 "대리인", "금액한도"입니다. | copy-guide 1.1 "대결자"("대리인" 안 씀) | web/src/mocks/inbox.ts:369-373(실제 서버 라벨은 그림이 없어 확인하지 못함) |
| R-5 | 완료 요약·지정 결과가 "~합니다"입니다("대결자로 지정합니다", "결재를 올립니다"). | copy-guide 2.3 "한 문장, 결과 먼저. '~했습니다'" | erp DelegationService.java:114 / [실제] stack-chat-done.png |
| R-6 | 기본 에이전트를 "전사 비서"로 부르고 "맞는 담당 AI가 없으면 전사 비서가 답합니다"라고 씁니다. 설명에 "부서 에이전트", "질의"가 있습니다. | copy-guide 1.5("총무 담당 AI가 답합니다", "질의 → 질문"), 1.2("AI 에이전트"·"재무 담당 AI") | [모의] light-agents.jpg / web/src/mocks/org.ts:48-53(실제 그림도 같은 문장이라 팩 정의 문구로 보임) |
| R-7 | 직원이 보는 AI 에이전트 화면에 라우팅 낱말("맡는 말")이 나옵니다. | copy-guide 1.2 "방식 이름(LLM, 낱말)은 관리 화면에만" | [모의] light-agents.jpg |
| R-8 | 빈 상태 "이 기간에 막은 요청이 없습니다.", 차단 이유 "권한 범위 없음"을 씁니다. | copy-guide 1.5 "정책 차단 / 권한 없음. 금지·막음은 쓰지 않음" | web/src/admin/MetricsPanel.tsx:119 / [모의] light-admin-metrics.jpg |
| R-9 | 감사 사유에 "부를 수 없습니다", "대결 등록"이 있습니다. | copy-guide 1.5 "부르다 → 사용", 1.1 "대결 지정" | [모의] M3-01-audit.jpg |
| R-10 | 감사 로그 종류 칸에 출처(erp, gateway, mcp)를 같은 칸에 붙여 씁니다. | copy-guide 1.4 "출처는 별도 칸" | [모의] light-admin-audit.jpg |
| R-11 | 감사 로그 결과·태그와 외부 전송 "가림 n곳"이 테두리 있는 알약 배지입니다(성공, 정책 차단, 실행 취소 가능/불가, 대기). | design-system 2.2·3.3 "점 + 글자, 배지 면 없음", 태그는 `--fill-2` 면 | [모의] light-admin-audit.jpg, light-admin-egress.jpg |
| R-12 | 감사 로그 실행 결과를 "성공"으로 씁니다. | copy-guide 1.2 실행 결과 "완료" | web/src/admin/AuditPanel.tsx |
| R-13 | 대결 지정 확인이 폼 아래에 붙는 카드입니다(뒤 막·초점 가둠 없음). | design-system 3.9 "새 대결 지정은 시트(대화상자), `--scrim`, Esc, 초점 가둠" | web/src/inbox/DelegationPanel.tsx:210(`section.sheet`가 흐름 안에 있음) |
| R-14 | 의견 칸에 칸 위 라벨이 없고 자리 표시 글 "의견"만 있습니다. | design-system 3.5 "라벨은 칸 위" | [모의] light-inbox-doc-delegated.jpg |
| R-15 | 결재선 사람에 직급이 없습니다("서도윤 결재 대기"). 결재 상세 문서 번호는 모의에서는 없고 실제에서는 내부 ID입니다. | design-system 3.7 "서도윤 팀장", "경비 정산 EXP-0107" | [모의] A1-01-doc.jpg / [실제] stack-approvals.png |
| R-16 | 승인·반려 뒤 다음 결재 대기 문서가 열리지 않습니다. | design-system 3.7 "승인·반려 뒤에는 목록에서 다음 결재 대기 문서가 열립니다" | [모의] A2-02-done.jpg |
| R-17 | 탐색 막대 결재 건수가 결재 대기와 대결 대기를 합친 수입니다. | design-system 3.1 "결재 대기 건수" | [모의] light-inbox.jpg(3 = 2 + 1) |
| R-18 | 합계 카드 숫자에 단위가 없습니다. | copy-guide 2.3 "숫자는 단위를 붙입니다" | [모의] light-admin-metrics.jpg |
| R-19 | "범위가 넓은 대결"이 용어집에 있지만 대결 지정 화면 어디에도 나오지 않습니다. | copy-guide 1.5 | web/src/inbox/FormScope.tsx, DelegationPanel.tsx(해당 표시 없음) |
| R-20 | 평가 조건 이름에 첫 등장 설명이 없고, 보고서 이름에 "정상 셋"이 남아 있습니다. | copy-guide 1.4 "첫 등장에 한 줄 설명", 1.5 "정상 세트" | [모의] light-eval.jpg |
| R-21 | 운영 지표 에이전트 이름이 "IT운영"입니다. | copy-guide 1.5 "IT운영팀(고유 이름)" | [실제] stack-ops-metrics.png |
| R-22 | 로그인 도움말이 "IT 담당 부서"입니다. | copy-guide 1.5 "IT운영팀" | [모의] light-login.jpg |

## 13. 추측과 세지 않은 것

- **탐색 막대에 두 항목이 칠해짐:** light-org·dark-org에서는 "AI 비서"와 "조직도"가, dark-admin-audit에서는 "운영 지표"와 "감사 로그"가 함께 칠해져 있습니다. 실제 stack-org.png에서는 "조직도" 하나만 칠해져서, 캡처할 때 마우스가 올라가 있던 흔적으로 보입니다.
- **캡처 부작용으로 보이는 것:** light-inbox-delegation-preview.jpg의 탐색 막대가 116px 아래로 내려가 있습니다. light-eval.jpg는 4340px 높이인데 800px 아래가 비어 있습니다(1440 폭 문서 그림 ops-eval-light.png에는 아래 내용이 있습니다). 둘 다 전체 페이지 캡처 때문으로 보여 세지 않았습니다.
- **모의 데이터 때문인 것:** 모의 감사 로그의 직원 ID가 "emp-2002"여서 사번 필터 예시(E0007)와 맞지 않습니다. 실제 그림은 "E0006"이라 모의 데이터 문제로 봤습니다. 대결 경비 정산 320,000원에 내역·영수증 칸이 없는 것은 팩 양식 필드 부족(명세 6절)으로 보입니다.
- **채팅 첨부 칩이 흐린 것:** E1-02·E2-01·E3-01·E5-02에서 "사진 첨부"가 비활성으로 보입니다. 응답 스트림이 아직 끝나지 않은 순간으로 보여 세지 않았습니다. C-1은 같은 순간의 목록 문제입니다.
- **그림이 없어 평가하지 못한 것:** 명령 팔레트(Ctrl K), 알림 목록, 사용자 메뉴(테마·로그아웃), 대결 해제 확인 팝오버, 반려 흐름, 대결 문서의 승인 확인 팝오버(누구 대신인지 다시 알리는지), 불러오는 중·네트워크 오류 상태, 좁은 폭(태블릿) 배치.
- **이후 커밋에서 고쳐져 세지 않은 실제 그림의 문제:** stack-approvals.png의 값 행 순서 뒤섞임(사유·종료일·종류·시작일 → #634), stack-agents.png의 도구 코드 이름 노출(→ #638), 메뉴 "평가 리포트"(→ #638·#639).
- **확인 카드 라벨 출처:** G-3·R-4의 "대리인/금액한도"는 모의 서버(`mocks/inbox.ts`) 문구입니다. 실제 erp가 같은 라벨을 돌려주는지는 그림이 없어 확인하지 못했습니다.
