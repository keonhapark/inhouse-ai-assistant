# 화면·안내 문구 전수 점검

사용자가 보는 문구 전부를 [copy-guide.md](copy-guide.md)(용어집과 문체 원칙)에 비춰 점검한 결과입니다(#572). 코드는 고치지 않았습니다. 반영은 모듈별 후속 이슈에서 합니다.

점검은 영역 넷으로 나눠 서브에이전트 네 개가 따로 했고, 모두 용어집을 먼저 읽은 뒤 코드를 읽기만 했습니다. 줄 번호는 각 점검이 실제 파일에서 확인한 것이고, 이 세션이 몇 줄을 뽑아 다시 확인했습니다(`gateway/gateway/erp_client.py:28`, `erp/.../common/Problems.java:18`, `erp/.../leave/LeaveService.java:52`, `erp/.../room/RoomService.java:76`, `web/src/api/client.ts:66`, `toolLabel` 채우는 곳 없음).

## 1. 한눈에

| 영역 | 범위 | 건수 | 직역투 | AI 말투 | 용어 불일치 | 어색함 | 표시 이름 없음 | 원문 |
|---|---|---|---|---|---|---|---|---|
| web | `web/src` 화면 문구·오류·빈 상태 | 106 | 19 | 2 | 55 | 30 | – | [copy-audit/web.md](copy-audit/web.md) |
| 슬랙·agent | `channels/slack`, agent 고정 문구·시스템 프롬프트 | 48 | 8 | 2 | 25 | 13 | – | [copy-audit/slack-agent.md](copy-audit/slack-agent.md) |
| gateway·erp | 사용자에게 돌아가는 오류(problem+json)·알림 | 99 | 22 | 0 | 46 | 31 | – | [copy-audit/gateway-erp.md](copy-audit/gateway-erp.md) |
| 팩 | `packs/` 에이전트·양식·필드·조직 표시 이름 | 44 | 4 | 0 | 20 | 11 | 9 | [copy-audit/packs.md](copy-audit/packs.md) |
| **합계** | | **297** | **53** | **4** | **146** | **85** | **9** | |

- 같은 문구가 여러 곳에 있으면 한 줄로 셌습니다.
- **용어 불일치가 절반입니다(146건).** 문장이 틀린 것보다 같은 개념을 화면·슬랙·오류·팩이 서로 다른 말로 부르는 것이 더 큰 문제입니다. 대표: 되돌리기/실행 취소, 위임/대결, 해지/해제, 요청자/기안자, 결재 차례/결재 대기, 처리함/결재 완료.
- **AI 말투는 적습니다(4건).** 고정 문구는 대체로 짧고 습니다체입니다. 남은 것은 시스템 프롬프트가 답의 말투를 정하지 않는 곳과 "~해 드릴게요"류 몇 군데입니다.
- **직역투 53건**의 대부분은 코드 값·영어 단어가 문장에 그대로 들어간 것입니다(`end_date가 start_date보다 앞입니다`, `since가 until보다 늦습니다`, "리소스", "행동이 없습니다").

## 2. 영역을 가로지르는 문제

개별 문구보다 먼저 고쳐야 효과가 큰 구조 문제입니다.

| 문제 | 근거 | 영향 | 어디서 |
|---|---|---|---|
| **오류 제목과 상세를 이어 붙여 같은 말이 두 번 나옴** | `web/src/api/client.ts:66`이 `title + detail`을 보여 줌. erp는 여러 오류에서 title과 detail이 같음(`Problems.java`·`ApprovalService.java:120` 등) | "본인이 올린 문서는 결재할 수 없습니다 본인이 올린 문서는 결재할 수 없습니다"처럼 보임 | web(표시 규칙), erp(detail 정리) |
| **도구 표시 이름이 비어 코드 이름이 나감** | 계약에 `toolLabel`이 있으나 gateway·agent에서 채우는 곳이 없음(웹·슬랙은 읽기만 함). 웹은 `display/names.ts`가 일부를 대신 듦 | 슬랙 카드 제목이 `실행 미리보기: room_reserve`처럼 나갈 수 있음 | 표시 이름을 둘 곳 결정(팩 또는 계약)은 리드 |
| **이름 뒤 조사를 "을"로 고정** | `erp/.../room/RoomService.java:76` `room.getName() + "을 "`, 결재·티켓 요약도 같음 | "회의실 C을 예약합니다" | erp(받침에 맞춘 조사 함수) |
| **할 일이 없는 오류 39개** | gateway 18, erp 21 | 직원이 무엇을 다시 해야 할지 모름 | gateway, erp |
| **코드 값이 문장에 그대로** | `문서 상태가 in_progress입니다`, `{operation}은 되돌릴 수 없습니다`, `local_only` | 직원에게 뜻이 없음 | erp, gateway(표시 이름 사전) |
| **팩의 표시 이름이 화면까지 오지 않음** | 팩에는 역할 "직원", 직급·부서 이름이 있으나 에이전트 정보에 실려 오지 않음. web이 제조 팩 직급 이름을 고정으로 들고 있음 | `역할 employee`, 금융·IT 서비스 팩에서 틀린 직급 이름 | 계약·gateway(표시 이름 전달), 팩 |

## 3. 후속 이슈 제안(리드가 나눔)

| 이슈(안) | 범위 | 근거 |
|---|---|---|
| web: 용어집 용어로 화면 문구를 바꾸고 오류 표시 중복을 없앱니다 | web 106건, 2절의 제목·상세 중복 | copy-audit/web.md |
| slack: 슬랙 메시지·버튼 문구를 용어집에 맞춥니다 | 슬랙 26건 | copy-audit/slack-agent.md 1절 |
| agent: 고정 안내 문구와 시스템 프롬프트의 말투 지침을 맞춥니다 | agent 22건, copy-guide 2.6 | copy-audit/slack-agent.md 2·3절 |
| gateway: 오류·차단 문구에 할 일을 더하고 코드 값을 표시 이름으로 바꿉니다 | gateway 34건 | copy-audit/gateway-erp.md |
| erp: 오류·알림 문구, 조사 처리, 제목·상세 중복을 고칩니다 | erp 65건, 2절의 조사 고정 | copy-audit/gateway-erp.md |
| 계약·팩: 도구·역할·직급의 표시 이름을 화면까지 전달합니다 | 표시 이름 없음 9건, 2절의 `toolLabel` | copy-audit/packs.md, 계약 변경 필요 여부는 리드 판단 |

용어를 바꾸는 순서는 계약·팩(표시 이름) → erp·gateway(오류 문구) → agent·슬랙·web(화면)이 덜 겹칩니다. 화면 용어가 바뀌면 [과업 걸어 보기](research/baseline.md) 스크립트(`ux/walkthrough/tasks.mjs`)의 찾는 이름도 함께 고칩니다(#564).

## 4. 점검이 정한 새 말

네 점검이 "용어집에 없다"고 한 말 57개(겹침 포함)는 copy-guide 1.5절에 정해 두었습니다. 금융·IT 서비스 팩의 업종 용어는 4단계 팩 작업 때 정합니다.
