# eval

평가 하네스입니다. 측정 설계는 [protocol.md](protocol.md)에 있습니다.

장치 구현 코드(`gateway/`, `agent/`, `rag/`의 판정·가림 규칙)를 보지 않고, 계약(`contracts/`)과 실행 기록만으로 판정합니다.

## 구성

| 파일 | 하는 일 |
|---|---|
| `harness/scenario.py` | 시나리오 읽기. 계약 스키마(`contracts/eval/scenario.schema.json`)와 추가 규칙(도구 이름, `${이름}` 참조, 정상·우려 조합)을 검사합니다 |
| `harness/erp.py` | operationId로 erp를 부릅니다. 메서드·경로는 `contracts/openapi/erp.yaml`에서 찾습니다 |
| `harness/setup.py` | 대화 전에 `setup`을 실행하고 `saveAs`로 리소스 ID를 저장합니다 |
| `harness/sut.py` | 평가 대상과의 경계. `GatewayChat`은 gateway 계약의 대화·실행 승인(SSE)·감사 조회를 씁니다 |
| `harness/conversation.py` | 발화, 실행 승인(시나리오의 `executionApprover`), 되묻기 응답(`clarifications`)으로 대화를 끝까지 진행합니다 |
| `harness/db.py` | 대화 직후, 되돌리기 전 `dbAssertions`를 JSONPath(RFC 9535)로 판정합니다 |
| `harness/judge.py` | 표지 문자열·금지 도구·DB 상태·외부 전송으로 사고를 판정하고 결과를 분류합니다 |
| `harness/run.py` | 한 회차: setup → 대화 → 기록 수집 → DB 판정 → 사고 판정 |

## 시험

```
cd eval
uv sync
uv run pytest -q
```

시험은 가짜 erp(`contracts/fakes/erp`)를 프로세스 안에서 띄우고, gateway·agent 자리에는 대본대로 답하는 계약 스텁(`tests/stub_system.py`)을 씁니다. 모델을 부르지 않습니다.

## 아직 없는 것

- 외부 LLM 요청 기록을 읽는 경로가 계약에 없습니다. 정해질 때까지 `GatewayChat(external_log=...)`에 수집기를 끼울 수 있게 두었고, 수집하지 못하면 판정 결과의 `notes`에 남깁니다.
