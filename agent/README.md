# agent

에이전트 등록부 런타임, 입구 라우터, 업무 실행(LangGraph), MCP 서버, 슬롯 파서 기준선입니다. API는 `contracts/openapi/agent.yaml`, 도구는 `contracts/mcp/tools.json`을 따릅니다.

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
  - `full`: 위험 등급이 에이전트 `allowed_risk` 밖이면 금지, 그 밖은 `risk_policy`(auto, auto_with_undo, confirm, deny)와 `overrides`를 따릅니다. `when: wide_scope`는 팩 `org.yaml`의 `delegation_policy.wide_scope`(기간, 금액 한도, 모든 양식)로 판단하고, 판단할 수 없으면 넓다고 봅니다. `when: {arg, gt}`는 도구 인자 `arg`가 `gt`보다 크면 맞고(같으면 맞지 않음), 인자가 없거나 숫자가 아니면 더 엄격한 쪽(override action)을 씁니다(고액 경비 정산·구매 요청 확인).
  - `no_guard`: 모두 바로 실행 / `write_blocked`: 쓰기 도구를 모델에 보이지 않고 호출도 막음 / `approve_all`, `baseline_tools`: 쓰기는 모두 승인
- 신뢰 등급(`full`만, `run/trust.py`): 한 턴 안에 신뢰 불가 출력이 들어오면 그 턴이 끝날 때까지 `trust_required=user_direct` 도구를 막습니다. 그 대화(`conversationId`)의 다음 턴부터는 `user_direct` 도구를 바로 실행하지 않고 미리보기 승인을 받습니다(대화가 끝날 때까지). 신뢰 불가 출력은 다른 사람이 쓴 자유 문장이 든 erp 출력(사유·제목·의견, 티켓 담당자 댓글 등, 작성자가 요청자가 아니거나 모름)과, 팩 `docs.yaml`에서 `trust: trusted`가 아닌 문서를 인용한 rag 답입니다. 신뢰 불가 출력에는 표시를 붙여 모델에 넘기고, 다음 턴을 시작할 때 그 본문을 기록에서 뺍니다. 모델이 쓴 문장과 막힌 호출의 인자는 기록에 남으므로, 앞 턴의 지시가 다음 턴 "진행해" 같은 짧은 답으로 실행되지 않게 승인 단계를 둡니다.
- confirm이면 erp 미리보기(dryRun)를 받아 `awaiting_approval`과 `pendingApproval`로 멈춥니다. `/resume`의 `approvalId`가 기다리는 것과 다르거나 이미 결정됐으면 409입니다. 거절하면 실행하지 않고 끝냅니다.
- 쓰기 실행은 `conversationId`와 도구 호출 ID로 만든 멱등 키를 씁니다. auto_with_undo로 실행한 되돌릴 수 있는 행동은 답 끝에 행동 ID와 함께 안내합니다.
- 요청자가 부를 수 없는 에이전트(fallback 포함, `callable_by`)면 도구 없이 안내만 합니다. 토큰의 에이전트·요청자·대화가 요청과 같은지 봅니다. 토큰 확인 키(`DELEGATION_TOKEN_PUBLIC_KEY`나 `DELEGATION_JWKS_URL`)가 없으면 시작하지 않고, 개발 때만 `AGENT_ALLOW_UNVERIFIED_TOKENS=1`로 끕니다.
- 도구 호출이 MCP 서버에 닿지 못하면 도구 오류로 모델에 돌려주고, 그래프 오류는 `failed`로 돌려줍니다(승인 대기 상태가 남지 않음).
- 상태: 막힌 도구 호출이 있으면 `blocked`, 답이 되묻기 모양("?", "~까요", "~주세요" 등)이면 `awaiting_user`, 모델·도구 목록 오류나 단계 초과(6번)는 `failed`
- 정책으로 막은 호출은 감사 이벤트 `tool.blocked`(source agent)로 남깁니다.

## 슬롯 파서 기준선(`POST /baseline/slots`)

기능 품질 비교용입니다. 휴가·회의실 요청에서 도구(`leave_request`, `room_list_availability`, `room_reserve`)와 인자를 채워 돌려주고, 실행하지 않습니다. `method: rule`은 LLM 없는 규칙 파서(`baseline/slots.py`), `method: llm`은 gateway를 거친 도구 호출 한 번(`baseline/llm_filler.py`)이고 둘 다 같은 형식(`intent`, `tool`, `arguments`, `missing`)을 돌려줍니다.

- 규칙 파서가 읽는 것: 날짜(YYYY-MM-DD, M월 D일, M/D, 오늘·내일·모레·글피, (이번·다음·다다음 주) X요일, 다음 달 N일·N째 X요일, N일), 기간(~부터 ~까지, N일간: 휴가는 주말 제외), 시각(오전·오후 N시 (반·M분), HH:MM, 앞뒤 문맥 없는 1~7시는 오후), 길이(N시간, N분간, 기본 1시간), 인원(N명·N인, 고유어 수), 휴가 종류(오전·오후 반차, 병가, 경조·공가·특별휴가, 그 밖은 연차), 사유("사유는 …", "…해서"), 회의실 이름(팩 `fixtures/rooms.json`)
- 사유가 없으면 "개인 사정", 회의 제목이 없으면 "회의"로 채웁니다. 오전·오후가 없는 "반차", 날짜·시각·회의실을 못 찾으면 `missing`에 적습니다.
- 규칙은 도구 입력 스키마만 보고 만들었고, 평가 시나리오를 보고 다듬지 않았습니다.

명령줄 비교: `uv run python -m agent_runtime.baseline --method both --today 2027-03-02 "다음 주 월요일 오후 반차"`

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
- 신뢰 등급과 위험 등급(`risk_policy`·`allowed_risk`)은 서버에서 판정하지 않습니다. `_meta.trustLevel`은 호출 쪽(LangGraph 실행부)이 대화 상태로 정한 값을 그대로 씁니다. 신뢰 표시는 대화 기록에 묶여 있어 서버가 알 수 없고, 평가 조건(`no_guard` 등)마다 위험 판정을 다르게 해야 해서 실행부에 둡니다. 서버를 부를 수 있는 것은 `aud`에 `mcp`가 든 위임 토큰을 가진 쪽뿐입니다.

도구 인자는 이름으로 erp 요청에 놓습니다: path 파라미터 → 경로, query 파라미터 → 쿼리, 본문 최상위 속성 → 본문, 본문 객체 속성 안의 이름(대결 위임 `scope.formTypes` 등) → 그 객체, 그 밖은 결재 양식 `fields`. `backend.fixed` 값은 같은 이름의 인자보다 우선하고, 그 이름을 입력 스키마에 두면 시작하지 않습니다. 경로 인자는 퍼센트 인코딩합니다.

## 첨부 영수증

`/run`의 `attachments`(jpeg·png data URL, 최대 3장)는 `expense_request` 도구가 있는 에이전트만 읽습니다(`run/receipt.py`). 그 밖의 에이전트는 "읽지 않았습니다"라는 안내만 붙입니다.

- 이미지는 위임 토큰을 붙여 gateway에 `image_url`로 보내고, gateway는 이미지가 든 요청을 로컬 비전 별칭으로만 보냅니다. 답은 JSON 스키마(금액·사용일·가맹점·사업자번호)로 받고, 형식이 맞는 값만 남깁니다(그 밖은 null)
- 읽은 값은 `[신뢰할 수 없는 내용…]` 표시로 감싸 사용자 메시지 뒤에 붙입니다. 비어 있는 값과 사용 목적은 사용자에게 묻도록 안내합니다
- 하나라도 읽으면 그 대화를 신뢰 불가 표시(`conversation_tainted`)로 둡니다. `user_direct` 도구(경비 정산 등)는 같은 턴이라도 막지 않고 미리보기 승인을 받은 뒤 실행합니다(결정 0004). 같은 턴 막음으로 두면 영수증으로는 정산을 올릴 수 없기 때문입니다
- 이미지 본문은 그래프 상태·감사·로그에 넣지 않습니다. 읽지 못하면(gateway 오류, JSON 아님) 표시 없이 사용자에게 값을 묻도록 안내합니다

## 평가 경로(도구 호출 측정)

`AGENT_EVAL_MODE=1`이면 `POST /eval/tool-call`을 켭니다(아니면 404). 업무 실행의 첫 계획 호출만 하고 도구를 실행하지 않습니다(MCP·erp를 부르지 않음). 위임 토큰 없이 gateway를 부릅니다. 채점은 eval이 합니다.

- 기본(S0): 업무 실행과 같은 시스템 프롬프트(`full`)와 에이전트 도구 목록(`contracts/mcp/tools.json`), 온도 0
- `grammar`: 첫 호출로 도구를 고르고, 둘째 호출에 그 도구 입력 스키마를 `response_format`(json_schema)으로 걸어 인자를 받습니다. 별칭이 구조화 출력을 지원하지 않으면 400입니다(`local`은 지원하지 않음, #205)
- `toolFilterK`: 요청 문장과 도구 설명의 두 글자 묶음 겹침이 큰 k개만 모델에 보입니다. 응답 `candidates`로 정답 도구가 남았는지 봅니다
- `fewShot`: `AGENT_EVAL_FEWSHOT`(기본 `eval_dev/tool_calls.jsonl`)에서 후보 도구마다 예시 하나를 시스템 프롬프트에 넣습니다. 평가하는 요청과 문장이 같은 예시는 뺍니다
- `thinking`: `reasoning_effort`를 `low`(켬)·`none`(끔)으로 보냅니다. null이면 보내지 않습니다
- 응답의 `model.egress`·`location`은 gateway 출구 헤더, `usage`는 호출 토큰 합(하나라도 없으면 null), `latencyMs`는 모델 호출 시간 합입니다
- 응답 `content`는 모델이 쓴 문장이라 감사·로그에 남기지 않습니다

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
| `AGENT_PACK_STAGE` | `pack.yaml`의 `stage` | 켤 단계. 에이전트·MCP 도구 모두 이 단계 이하만 켭니다 |
| `AGENT_AUDIT_LOG` | `var/audit.jsonl` | 감사 이벤트 파일 |
| `AGENT_ROUTER_MIN_CONFIDENCE` | `0.5` | LLM 라우터 확신도가 이보다 낮으면 fallback |
| `AGENT_LLM_BACKEND` | `gateway` | `gateway` 또는 `ollama`(gateway가 없을 때 쓰는 개발용) |
| `GATEWAY_LLM_URL` | `http://localhost:$PORT_GATEWAY/v1` | gateway의 OpenAI 호환 엔드포인트 |
| `AGENT_OLLAMA_BASE_URL` | `http://localhost:11434` | 개발용 Ollama 주소 |
| `AGENT_LLM_MODEL` | gateway: `local`, ollama: `LOCAL_MODEL` 또는 `qwen3.5:9b` | 라우터·슬롯 기준선의 모델. 업무 실행은 gateway 경로에서 에이전트 `model_policy`대로 별칭을 고릅니다(`external_allowed` → `external`, `local_only` → `local`). 평가 조건 `no_guard`·`baseline_tools`는 모두 `external`입니다(`contracts/eval/conditions.md`). 기밀 판정에 따른 로컬 전환은 gateway가 합니다 |
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
