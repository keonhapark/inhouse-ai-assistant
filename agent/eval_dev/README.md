# 개발 묶음(도구 호출)

로컬 모델 도구 호출 측정(#103)의 개발 묶음 60개입니다. few-shot 예시와 프롬프트 다듬기에 씁니다. 확인 묶음(120개)은 다른 작성자가 이 저장소의 구현을 보지 않고 따로 쓰며, 이 파일과 겹치지 않게 합니다.

## 형식

`tool_calls.jsonl`에 한 줄에 항목 하나입니다(확인 묶음과 같은 형식).

```json
{"id": "dev-001", "agentId": "hr", "requester": "E0016", "today": "2026-11-20",
 "message": "다음 주 월요일 연차 쓸게요",
 "expect": {"tool": "leave_request", "arguments": {"leave_type": "annual", "start_date": "2026-11-23", "end_date": "2026-11-23"}},
 "tags": ["stage1", "leave"]}
```

- `expect`는 셋 중 하나입니다: `{"tool", "arguments"}`(첫 도구 호출), `{"ask": true, "why": "ambiguous_date|same_name|missing_field"}`(되물어야 함), `{"refuse": true}`(이 에이전트가 하면 안 되는 일)
- `arguments`는 필수 인자만 적고, 날짜·시각은 ISO(`+09:00`)입니다. 자유 문장 인자(`reason`, `title`, `purpose`, `question`, `q`)는 적지 않습니다(채점에서 뺌)
- 대상을 먼저 찾아야 하는 요청(대결 위임처럼 사람 이름만 있는 것)은 첫 호출을 `org_search_employees`로 적습니다
- 기준일은 2026-11-20(금)입니다. 직원 ID는 팩 `fixtures/employees.json`, 회의실 ID는 `fixtures/rooms.json`입니다. 결재 문서·위임·예약·품목 번호는 가상 값입니다
- 구성: 에이전트 넷(assistant, hr, finance, procurement), 도구 호출 44, 되묻기 10, 거절 6

`tests/test_eval_dev_set.py`가 형식, 팩·도구 계약(입력 스키마)과의 일치, 구매 합계(수량 × 단가)를 확인합니다.
