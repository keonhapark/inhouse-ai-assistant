# 개발 묶음(도구 호출)

로컬 모델 도구 호출 측정(#103)의 개발 묶음 60개입니다. few-shot 예시와 프롬프트 다듬기에 씁니다. 확인 묶음(`tc-001`~`tc-120`)은 다른 작성자가 이 저장소의 구현을 보지 않고 따로 쓰며, 이 파일과 겹치지 않게 합니다.

## 형식

`tool_calls.jsonl`은 `contracts/eval/toolcall/`의 toolcall-v1 형식(`item.schema.json`)이고, 채점 규칙도 같은 폴더 README를 따릅니다.

- 번호는 확인 묶음과 겹치지 않게 `tc-901`~`tc-960`입니다
- 기준일은 모두 2027-03-10(수)입니다. 직원 ID는 팩 `fixtures/employees.json`, 회의실 ID는 `fixtures/rooms.json`입니다. 결재 문서·위임·예약·품목 번호는 가상 값이고 `setup`은 쓰지 않습니다
- 구성: direct 36, clarify 11, resolve 9, confusable 4. `targetTool`이 2단계 도구(`expense_request`, `purchase_request`)인 항목은 12개입니다
- 자유 문장 인자(`reason`, `title`, `purpose`, `question`, `q`)는 `argMatch: nonempty`, 발화에 나온 가맹점 이름은 `normalized`, 대결 기간은 `date`, 양식 목록은 `set`입니다
- 사유가 필수인 쓰기 도구는, 발화에 사유가 없으면 정답을 되묻기(`clarify`)로 둡니다(지어내지 않음)

`tests/test_eval_dev_set.py`가 형식, 팩·도구 계약(입력 스키마)과의 일치, 구매 합계(수량 × 단가)를 확인합니다.

## 경로 확인 실행

`smoke_run.py`는 이 묶음을 실제 agent 평가 경로(`POST /eval/tool-call`)로 한 번 돌립니다. 채점기가 아닙니다(채점·측정은 eval #237). 항목에 에이전트가 없어 `targetTool`을 가진 에이전트를 hr, assistant, finance, procurement 순으로 고릅니다.

```bash
uv run python eval_dev/smoke_run.py --url http://localhost:$PORT_AGENT \
  --out eval_dev/runs/<이름>.jsonl --model local --variant '{"thinking": false}'
```

기록은 `runs/`에 있습니다. 결과 줄에는 모델이 쓴 문장(`content`)이 들어 있습니다(가짜 데이터).

| 실행 | 조건 | 결과(60개, 1회) |
|---|---|---|
| `runs/2026-11-21-local-s0-nothink.jsonl` | 2026-11-21 00:17 KST. S0, `local`(qwen3.5:9b, digest d63f830f28d5, MLX 실행기), `thinking: false`, 온도 0. Ollama 0.40.15, Apple M1 Pro 32GB, 공용 Ollama(다른 세션 호출 있음) | HTTP 200 59개(1개는 agent LLM 시간 제한 60초 초과로 502). 첫 행동 이름 일치 24. 도구 호출이 정답인 48개 중 25개는 도구를 부르지 않고 확인·되묻기를 했습니다(그중 `asked` 판정은 7개). 되묻기 정답 11개 중 `asked` 판정 2개. 모델 호출 지연 p50 4.3초, p95 12.5초 |

이 실행에서 본 것(측정 결과가 아님, 판단은 eval이 함)
- 필요한 값이 모두 있어도 먼저 확인을 묻는 답이 많습니다(쓰기 도구에서 두드러짐). 선택 인자(`business_no`)를 필수처럼 묻기도 합니다.
- 되묻기 판정(마지막 줄이 물음 모양)은 "알려주시면 ~하겠습니다."로 끝나는 되묻기를 놓칩니다.
