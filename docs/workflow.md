# 작업 방식

모듈 세션 여러 개가 각자 worktree에서 동시에 일합니다. 이 문서는 누가 어디를 고치고, 어떤 순서로 이슈를 처리하고, 막히면 어떻게 하는지 적습니다. 커밋·브랜치·PR 형식은 `docs/conventions.md`입니다.

## 1. 모듈과 담당 경로

| 세션 | 모듈 | 담당 경로 | 언어·기술 | 시작 단계 |
|---|---|---|---|---|
| S0 | 프로젝트 리드(계약·팩·통합) | `contracts/`, `packs/`, `infra/`, `scripts/`, `.github/`, `docs/`(아래 예외 빼고), 루트 파일 | OpenAPI 3.1, JSON Schema 2020-12, Python | 0 |
| S1 | erp | `erp/` | Java 21, Spring Boot 3, Spring Security(JWT), JPA, PostgreSQL | 1 |
| S2 | gateway | `gateway/` | Python, FastAPI, LiteLLM, Presidio, Ollama | 1 |
| S3 | agent | `agent/` | Python, MCP Python SDK, LangGraph | 1 |
| S4 | rag | `rag/` | Python | 1 |
| S5 | eval | `eval/` | Python, pytest | 1 |
| S6 | web | `web/` | React, TypeScript, Vite | 1 |
| S7 | incident | `incident/` | Python(erp 세션이 맡음) | 2 |
| S8 | slack | `channels/slack/` | TypeScript, Slack Bolt(Socket Mode)(web 세션이 맡음) | 2 |

- 모듈 세션은 자기 경로만 고칩니다. 예외로 `docs/contract-requests.md`에 한 줄 더하는 것은 누구나 합니다.
- CI `paths` job이 브랜치 이름(`feat/<모듈>-…`)의 모듈과 바뀐 파일을 대조해 경로 밖 변경이 있으면 실패합니다.
- 코어(`erp/`, `gateway/`, `agent/`, `rag/`)에는 부서 이름·회사 이름 같은 업종 용어를 코드로 쓰지 않고 `packs/<업종>/`에서 읽습니다. CI `contracts` job이 검사합니다(시험 폴더 제외).
- `eval/`은 장치 구현 코드(`gateway/`, `agent/`, `rag/`의 판정 규칙)를 보지 않고 계약과 결과만 봅니다.

## 2. 이슈 루프(모듈 세션)

1. 자기 모듈 라벨이 붙고 `blocked`·`epic`이 아닌 열린 이슈 중 번호가 가장 작은 것을 고릅니다(`gh issue list -l <모듈> -s open`). `epic`은 2단계 뒤의 큰 범위라 리드가 그 단계에 들어갈 때 세부 이슈로 쪼갭니다. `blocked` 이슈라도 `blocked by`의 이슈가 모두 닫혔으면 라벨을 떼고 고릅니다. 이슈에 자기를 담당으로 적는 대신 코멘트로 "시작"을 남깁니다.
2. 최신 `develop`에서 브랜치를 만듭니다: `git fetch origin && git switch -c feat/<모듈>-<주제> origin/develop`
3. 구현하고 시험을 붙입니다. 모듈 시험이 로컬에서 통과해야 합니다.
4. PR을 엽니다. 제목은 커밋 형식, 본문은 PR 양식, `Closes #<번호>`를 적습니다.
5. 필수 검사 `ci-summary`가 통과하면 직접 squash 병합하고 브랜치를 지웁니다: `gh pr merge <번호> --squash --delete-branch`
6. 최신 `develop`을 받고 1로 돌아갑니다.

- 실패한 검사는 고쳐서 다시 올립니다. 검사를 끄거나 건너뛰지 않습니다.
- 막히면 프로젝트 리드에게 묻고(오케스트레이션 `ask`), 답을 기다리는 동안 다른 이슈를 합니다.
- 할 일이 없을 때 차례를 끝내지 않습니다. 리드와 모듈 세션 모두 `orca orchestration check --wait --timeout-ms 900000`으로 메시지가 올 때까지 기다리고, 메시지가 오면 처리한 뒤 다시 같은 명령으로 기다립니다. 시간이 다 되어도 다시 기다립니다. 사용자가 직접 말을 걸면 그쪽이 먼저입니다.
- 리드가 이슈를 맡길 때는 우편함 메시지 대신 `orca orchestration dispatch --task <id> --to <핸들> --inject`로 받는 터미널에 바로 넣습니다.
- 터미널 한 줄 알림(`orca terminal send --terminal <핸들> --text "우편함 확인" --enter`)은 `check --wait`가 돌지 않는 세션(다시 띄운 세션 등)에만 씁니다.
- 멈추는 때: 자기 모듈 이슈가 다 떨어졌을 때, 사용자 결정이 필요할 때. 이때 프로젝트 리드에게 알립니다.
- 계약과 구현이 어긋나면 계약이 기준입니다. 계약을 바꿔야 하면 아래 4절을 따릅니다.

## 3. 의존과 순서

- 의존은 이슈 본문의 `blocked by #<번호>`와 `blocked` 라벨로 적습니다. `blocked by`의 이슈가 모두 닫히면 모듈 세션이 직접 라벨을 떼고(`gh issue edit <번호> --remove-label blocked`) 시작합니다. 리드를 기다리지 않습니다.
- 남을 기다리지 않도록 각 모듈은 계약과 가짜로 먼저 만듭니다.
  - agent·eval·gateway는 가짜 erp(`contracts/fakes/erp`)를 씁니다.
  - gateway는 rag·agent를 계약 스텁으로 대신합니다.
  - web은 gateway 계약(`contracts/openapi/gateway.yaml`)의 모의 서버로 먼저 만듭니다.
- 마일스톤: `1단계`, `2단계`, `3단계`, `업종 팩`

## 4. 계약·팩 변경

- 기존 계약을 깨지 않는 추가(선택 필드, 새 경로·도구·이벤트, 팩 항목)는 요청한 모듈 세션이 직접 고칩니다.
  1. `contract` 라벨 이슈를 열고 `docs/contract-requests.md`에 한 줄 적습니다.
  2. `contract/<모듈>-<주제>` 브랜치에서 계약과 그 계약 시험·가짜 erp만 고치고 PR을 올립니다(구현 코드는 따로 모듈 PR로).
  3. PR을 프로젝트 리드에게 알리고(`--type question`), 리드가 PR에 승인 코멘트를 단 뒤 병합합니다. 다른 모듈에 영향이 있으면 리드가 그 모듈에 알립니다.
- 기존 계약을 깨는 변경(필드 삭제·이름 변경·필수로 바꿈, 의미 변경)과 루트 파일(compose, CI)은 프로젝트 리드가 합니다. 이슈로 요청합니다.
- 하위 호환을 깨는 변경은 단계 중간에 하지 않습니다. 1단계 1일차 끝에 개정 창구를 한 번 엽니다.

- 검수 세션(review)은 병합된 PR이 기획서·결정 기록·계약에 맞는지 보고, 어긋나면 해당 모듈 라벨과 `bug`로 이슈를 엽니다. 코드는 고치지 않습니다.

## 5. 실행 환경

- 포트와 compose 이름은 세션 번호로 나눕니다(`docs/ports.md`). `source scripts/env.sh <세션 번호>`
- `.env`는 `.worktreeinclude`로 worktree에 복사됩니다. 값은 커밋하지 않습니다.
- 위임 토큰 개발 키: `bash scripts/dev-keys.sh`(커밋하지 않음)
- 로컬 모델 Ollama(`qwen3.5:9b`)는 한 대를 모든 세션이 같이 씁니다(11434). 측정 기록은 `docs/measurements/`입니다.

## 6. 각 모듈이 갖출 것

- 시험 명령: Python 모듈은 `<모듈>/pyproject.toml`과 `uv run pytest`(CI가 `uv sync --frozen`을 쓰므로 `uv.lock` 커밋), erp는 `erp/gradlew test`, web은 `npm ci`·`npm run build`(`lint`·`test` 스크립트가 있으면 같이 돎)
- erp는 `erp/ci/start.sh`를 둡니다. 8040 포트에 erp를 띄우고 건강해질 때까지 기다리는 스크립트입니다. CI가 이것으로 `contracts/tests/test_erp_behavior.py`를 실제 erp에 돌립니다. 기능을 나눠 만드는 동안은 `erp/ci/behavior-tests.txt`(시험 이름 한 줄에 하나)에 구현한 시험만 적어 그것만 돌리고, 마지막 erp 이슈에서 이 파일을 지워 전체를 돌립니다.
- 실행 이미지: `<모듈>/Dockerfile`과 건강 확인(`GET /health`, erp는 `GET /api/v1/health`). `infra/compose.yaml`의 `full` 프로필이 이것을 씁니다.
- 감사·추적 이벤트는 `contracts/events/`의 형식으로 JSON Lines에 씁니다.
