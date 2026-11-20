# agent

에이전트 등록부 런타임, 입구 라우터, 업무 실행(LangGraph), MCP 서버입니다. API는 `contracts/openapi/agent.yaml`, 도구는 `contracts/mcp/tools.json`을 따릅니다.

- `GET /agents`: `PACK_DIR`의 `agents.yaml`에서 팩 단계(`pack.yaml`의 `stage`) 이하로 켜진 에이전트를 돌려줍니다.
- `POST /route`: 요청을 에이전트 하나에 한 번만 넘깁니다.
  - `method: llm`(기본): 등록부의 설명·예시를 프롬프트에 넣고 모델이 하나를 고릅니다. 모델 호출은 gateway의 OpenAI 호환 엔드포인트로 합니다.
  - `method: keyword`: `routing.keywords`가 가장 많이 든 에이전트를 고르는 기준선입니다. 비교 평가에 씁니다.
  - 고르지 못하면(맞는 것 없음, 동점, 확신도 미달, 모델 오류) `fallback_agent`가 받습니다. 고른 에이전트를 요청자가 부를 수 없으면(`callable_by`) 역시 `fallback_agent`가 받고, 고른 에이전트는 `suggestedAgentId`로 안내만 합니다. `fallback_agent`는 받을 곳이 없어지지 않도록 `callable_by` 검사 없이 받습니다(이때 쓸 수 있는 도구는 실행 단계에서 따로 막아야 합니다).
  - 모델이 확신도를 주지 않으면 기준 확인 없이 받아들입니다(`callable_by` 검사는 그대로 거칩니다).
  - 결정마다 감사 이벤트 `route.decided`를 JSON Lines로 남깁니다. 요청 원문과 모델이 쓴 이유 문장은 감사 기록에 넣지 않습니다.

업종 용어(부서·에이전트 이름)는 코드에 두지 않고 모두 팩에서 읽습니다.

## 업무 실행(`/run`, `/resume`)

LangGraph로 계획 → 판정 → 미리보기 → 승인 interrupt → 실행 → 되돌리기 안내를 잇습니다. thread_id는 `conversationId`이고 1단계 체크포인트는 프로세스 메모리(`InMemorySaver`)입니다.

- 모델은 gateway의 OpenAI 호환 엔드포인트로 부르고, 도구는 MCP 서버(`AGENT_MCP_URL`)로 부릅니다. 위임 토큰은 두 곳 모두 요청 헤더로만 넘기고, 모델 문맥과 그래프 상태에는 넣지 않습니다.
- 도구 호출마다 판정합니다(`run/policy.py`).
  - `full`: 위험 등급이 에이전트 `allowed_risk` 밖이면 금지, 그 밖은 `risk_policy`(auto, auto_with_undo, confirm, deny)와 `overrides`를 따릅니다. `when: wide_scope`는 팩 `org.yaml`의 `delegation_policy.wide_scope`(기간, 금액 한도, 모든 양식)로 판단하고, 판단할 수 없으면 넓다고 봅니다.
  - `no_guard`: 모두 바로 실행 / `write_blocked`: 쓰기 도구를 모델에 보이지 않고 호출도 막음 / `approve_all`, `baseline_tools`: 쓰기는 모두 승인
- 신뢰 등급(`full`만, `run/trust.py`): 한 턴 안에 신뢰 불가 출력이 들어오면 그 턴이 끝날 때까지 `trust_required=user_direct` 도구를 막습니다. 신뢰 불가 출력은 다른 사람이 쓴 자유 문장이 든 erp 출력(사유·제목·의견 등, 작성자가 요청자가 아니거나 모름)과, 팩 `docs.yaml`에서 `trust: trusted`가 아닌 문서를 인용한 rag 답입니다. 신뢰 불가 출력에는 표시를 붙여 모델에 넘깁니다.
- confirm이면 erp 미리보기(dryRun)를 받아 `awaiting_approval`과 `pendingApproval`로 멈춥니다. `/resume`의 `approvalId`가 기다리는 것과 다르거나 이미 결정됐으면 409입니다. 거절하면 실행하지 않고 끝냅니다.
- 쓰기 실행은 `conversationId`와 도구 호출 ID로 만든 멱등 키를 씁니다. auto_with_undo로 실행한 되돌릴 수 있는 행동은 답 끝에 행동 ID와 함께 안내합니다.
- 요청자가 부를 수 없는 에이전트(fallback 포함, `callable_by`)면 도구 없이 안내만 합니다. 토큰을 확인할 키가 있으면 토큰의 에이전트·요청자·대화가 요청과 같은지 봅니다.
- 상태: 막힌 도구 호출이 있으면 `blocked`, 답이 되묻기 모양("?", "~까요", "~주세요" 등)이면 `awaiting_user`, 모델·도구 목록 오류나 단계 초과(6번)는 `failed`
- 정책으로 막은 호출은 감사 이벤트 `tool.blocked`(source agent)로 남깁니다.

## MCP 서버

Streamable HTTP로 `/mcp`에 있습니다(compose 포트 8001). 도구 이름·설명·입력 스키마는 `tools.json` 그대로이고, 팩 단계 이하이면서 켜진 에이전트의 등록부에 있는 도구만 노출합니다.

- 위임 토큰은 HTTP 헤더 `X-Delegation-Token`으로만 받습니다. ES256 서명(gateway 공개 키), `iss=gateway`, `aud`에 `mcp`, 만료를 확인합니다.
- 토큰이 맞으면 `tools/list`는 그 토큰으로 부를 수 있는 도구만 돌려줍니다. 토큰이 없으면 노출된 도구 전부를 설명용으로 돌려줍니다.
- 호출을 막는 경우: 토큰 없음·틀림, 토큰 `tools`에 없음, 토큰 에이전트(`agt`)의 등록부에 없음, `trust_required=user_direct`인데 요청 `_meta.trustLevel`이 `user_direct`가 아님, 입력 스키마 위반. 결과는 `isError`와 `urn:problem:<코드>`입니다.
- erp에는 토큰을 `Authorization: Bearer`로, rag에는 `X-Delegation-Token`으로 넘깁니다. erp의 scope 검사 결과(403 등)는 그대로 돌려줍니다.
- 쓰기 도구는 `_meta.dryRun=true`면 erp 미리보기(`?dryRun=true`)를, 아니면 `_meta.idempotencyKey`를 `Idempotency-Key`로 넘겨 실행합니다.
- 도구 메타데이터: `annotations.readOnlyHint`(read), `annotations.destructiveHint`(irreversible), `_meta`의 `risk`, `trustRequired`, `requiredScope`, `stage`
- 사람 화면 전용 operation(`x-human-only`, 결재 승인·반려)에 묶인 도구가 있으면 시작하지 않습니다.
- 호출마다 감사 이벤트(`tool.called`, `tool.blocked`)를 남깁니다. 인자는 `argsHash`만 남기고, 토큰 문자열은 넣지 않습니다.

도구 인자는 이름으로 erp 요청에 놓습니다: path 파라미터 → 경로, query 파라미터 → 쿼리, 본문 최상위 속성 → 본문, 본문 객체 속성 안의 이름(대결 위임 `scope.formTypes` 등) → 그 객체, 그 밖은 결재 양식 `fields`. `backend.fixed` 값은 같은 이름의 인자보다 우선하고, 그 이름을 입력 스키마에 두면 시작하지 않습니다. 경로 인자는 퍼센트 인코딩합니다.

## 실행

```bash
cd agent
uv sync
# API만
PACK_DIR=../packs/manufacturing uv run uvicorn --factory agent_runtime.app:create_app --port 8320
# API(AGENT_PORT)와 MCP 서버(MCP_PORT)를 함께
PACK_DIR=../packs/manufacturing DELEGATION_TOKEN_PUBLIC_KEY=../infra/dev-keys/delegation-es256.pub.pem \
  AGENT_PORT=8320 MCP_PORT=8321 ERP_BASE_URL=http://localhost:8341/api/v1 uv run python -m agent_runtime.serve
```

| 환경 변수 | 기본값 | 뜻 |
|---|---|---|
| `PACK_DIR` | (필수) | 업종 팩 폴더 |
| `AGENT_AUDIT_LOG` | `var/audit.jsonl` | 감사 이벤트 파일 |
| `AGENT_ROUTER_MIN_CONFIDENCE` | `0.5` | LLM 라우터 확신도가 이보다 낮으면 fallback |
| `AGENT_LLM_BACKEND` | `gateway` | `gateway` 또는 `ollama`(gateway가 없을 때 쓰는 개발용) |
| `GATEWAY_LLM_URL` | `http://localhost:$PORT_GATEWAY/v1` | gateway의 OpenAI 호환 엔드포인트 |
| `AGENT_OLLAMA_BASE_URL` | `http://localhost:11434` | 개발용 Ollama 주소 |
| `AGENT_LLM_MODEL` | `LOCAL_MODEL` 또는 `qwen3.5:9b` | 모델 이름 |
| `AGENT_MCP_URL` | `http://localhost:$MCP_PORT/mcp` | 업무 실행이 부르는 MCP 서버 |
| `CONTRACTS_DIR` | `../contracts` | `mcp/tools.json`과 `openapi/`를 읽는 곳 |
| `ERP_BASE_URL` | `http://localhost:8040/api/v1` | erp(호스트까지만 씀. 경로는 계약의 `/api/v1`) |
| `RAG_BASE_URL` | `http://localhost:8030` | rag |
| `DELEGATION_TOKEN_PUBLIC_KEY` | | 위임 토큰 공개 키 PEM 파일. 없으면 `DELEGATION_JWKS_URL` |
| `DELEGATION_JWKS_URL` | | gateway JWKS |

## 시험

```bash
cd agent
uv run pytest -q
```

MCP 시험은 프로세스 안의 가짜 erp(`contracts/fakes/erp`)와 시험용 ES256 키로 돕니다. `tools/list` 응답 스냅숏은 `tests/snapshots/mcp_tools_list.json`이고, 의도한 변경이면 `UPDATE_SNAPSHOTS=1`로 다시 만듭니다.

LLM 라우터 시험은 `tests/recordings/router_llm.json`에 녹화한 모델 응답으로 돕니다. 녹화본에 없는 요청이 오면 실패합니다. 프롬프트나 등록부를 바꿨으면 다시 녹화합니다.

```bash
AGENT_LLM_RECORD=1 AGENT_LLM_BACKEND=ollama AGENT_LLM_CALL_BUDGET=20 uv run pytest -q tests/test_router.py
```

녹화 때 실제 호출은 시험 세션 하나에서 `AGENT_LLM_CALL_BUDGET`(기본 40)번까지만 합니다. 로컬 모델을 여러 작업이 같이 쓰기 때문입니다.
