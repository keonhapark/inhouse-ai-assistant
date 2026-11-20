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
| `harness/runner.py` | 다섯 조건 × 반복 실행, 실행 정보(커밋·시드·비용 상한) |
| `harness/stats.py` | Wilson·Clopper-Pearson 구간, Newcombe 짝 비교 구간, pass^k |
| `harness/report.py` | 회차별 결과로 보고서(`reports/`) |
| `harness/cli.py` | `validate`, `run`, `report` 명령 |

## 실행

```
cd eval
uv run python -m harness.cli validate scenarios
cp conditions.example.yaml conditions.local.yaml   # 주소·상한을 고침
uv run python -m harness.cli run --config conditions.local.yaml \
  --scenarios scenarios --set dev --out reports/<날짜>-dev-<요지>
uv run python -m harness.cli report reports/<이름>.json -o reports/<이름>.md
```

- 회차마다 `<이름>.rows.jsonl`에 한 줄씩 씁니다. 끊기면 같은 명령에 `--resume`을 붙여 끝난 회차를 건너뛰고 이어 돌립니다. 실행 환경 문제(gateway·erp 연결 실패, 재시도 가능한 오류 뒤 모델 서버 무응답)로 끝나지 못한 회차만 같은 회차 2번까지 다시 돌리고, 그 밖의 오류는 실패로 끝남으로 남깁니다(`eval/protocol.md` 2절). 모델 서버 확인은 설정 `modelHealth`로 켭니다.
- `--max-runs N`이면 이번 실행은 새 회차 N개까지만 돌리고 멈춥니다. `--resume`과 같이 써서 여러 번에 나눠 돌립니다.
- `--set normal`이면 정상 셋만, `--only <ID,...>`면 지정한 시나리오만 돌립니다.
- 설정의 `notes`는 보고서 실행 정보에 그대로 적힙니다(프로토콜과 다르게 돌린 이유 등).

## 시험

```
cd eval
uv sync
uv run pytest -q
```

시험은 가짜 erp(`contracts/fakes/erp`)를 프로세스 안에서 띄우고, gateway·agent 자리에는 대본대로 답하는 계약 스텁(`tests/stub_system.py`)을 씁니다. 모델을 부르지 않습니다.

## 실행 환경(평가 전용 설정)

- gateway: `GATEWAY_EVAL_MODE=1`(조건 헤더 `X-Eval-Condition`), `GATEWAY_EXTERNAL_LOG=<파일>`(외부로 보낸 요청 본문, `contracts/events/external-request.schema.json`). 설정의 `gateway.externalLog`에 같은 파일을 적습니다.
- erp: `ERP_EVAL_RESET=1`. 실행기가 회차마다 `POST /_eval/reset`으로 팩 고정 데이터 상태로 되돌립니다.
- rag: `RAG_MARKERS_FILE`(제한 문서 표지, 개발 셋은 `eval/markers/dev.yaml`), `RAG_EXTRA_DOCS`(주입 문서, 개발 셋은 `eval/injections/dev.yaml`). 확인 셋 파일은 작업 공간 밖 경로로만 넘깁니다.
