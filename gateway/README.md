# gateway

web이 부르는 유일한 서버입니다. 계약은 `contracts/openapi/gateway.yaml`(서버 기준 경로 `/api`)입니다.

지금 있는 것(1단계 #8~#11):

- `GET /health`, `GET /api/health`
- `GET /api/.well-known/jwks.json`: 위임 토큰 검증용 공개 키. `kid`는 RFC 7638 지문입니다.
- `POST /api/auth/login`, `GET /api/me`: erp에 그대로 넘기고 상태 코드와 본문을 그대로 돌려줍니다.
- 위임 토큰 발급(`gateway/delegation.py`): 대화마다 ES256, 10분. 클레임은 `contracts/auth/delegation-token.schema.json`입니다.
  - `scopes`: 라우팅된 에이전트 도구(`agents.yaml`의 `tools`)의 `required_scope`에서 사람 화면 전용 scope를 뺀 것입니다.
    직원 JWT는 erp에서 모든 scope를 가지므로, 요청자 쪽 제한은 erp가 "토큰 주인의 권한 ∩ 토큰 scopes"로 다시 봅니다.
  - `doc_scopes`: erp `/me/access-tags` ∩ 에이전트 `doc_scopes`
  - 에이전트 `callable_by`에 맞지 않는 요청자는 403입니다.
- LLM 출구 `POST /v1/chat/completions`(OpenAI 호환, `/api` 밖): 정책을 확인한 뒤 LiteLLM 프록시로 넘깁니다(`gateway/egress.py`).
  - `model`은 `litellm/config.yaml`의 별칭만 받습니다: `local`(Ollama `qwen3.5:9b`, 문맥 8192), `external`(Claude Haiku 5.5, `claude-haiku-5-5`).
    별칭마다 `model_info.location`이 있고, gateway는 이것으로 로컬·외부를 가릅니다.
  - `X-Delegation-Token`이 있으면 서명·만료를 확인하고 `agt`의 `model_policy`를 따릅니다. `local_only` 에이전트와
    토큰 없는 호출은 `external`을 쓰면 403 `model-policy`이고, 밖으로 아무것도 나가지 않습니다.
  - 토큰 헤더는 LiteLLM으로 넘기지 않고, 본문의 토큰 모양 문자열도 가린 뒤 보냅니다.
  - 기록(`GATEWAY_AUDIT_DIR`, 기본 `gateway/var/`, 커밋하지 않음): `audit.jsonl`에 감사 이벤트 `llm.request`
    (모델, 외부 전송 여부, 결과), `egress.jsonl`에 외부로 나간 요청의 가림 전후 본문과 응답. `egress.jsonl`은 원문이
    들어 있어 접근을 제한해야 하는 파일입니다.
  - 시간 제한(`LLM_TIMEOUT_SECONDS`, 기본 60초) 초과는 504 `llm-timeout`, 연결 실패는 502 `llm-unavailable`,
    LiteLLM 5xx는 502 `llm-upstream-error`이고, 모두 실패 알림(오류 로그, `ALERT_WEBHOOK_URL`이 있으면 웹훅)을 보냅니다.
  - 스트림(`"stream": true`)은 받은 대로 흘려보내고, 끝나면 기록합니다.
  - 별칭 설정 `model_info.drop_params`에 적은 필드는 보내기 전에 뺍니다. `external`(Claude Haiku 5.5)은 기본값이 아닌
    `temperature`·`top_p`를 400으로 거절해 둘을 뺍니다(LiteLLM 1.108.1도 빼지만 판이 바뀌어도 안전하게).
    `reasoning_effort`는 LiteLLM이 `thinking: adaptive`와 `output_config.effort`로 바꿔 넘깁니다(실측).
  - 출구가 요청을 거절하면(형식 422, 인증 401, 정책·등록부 403, 미지원 400) 감사 이벤트 `llm.request`에 대화 ID, 에이전트,
    요청한 별칭, 상태와 이유를 남깁니다(본문은 넣지 않음).
  - `response_format`: `model_info.supports_response_format: false`인 별칭(`local`, Ollama MLX 실행기의 qwen3.5:9b)은 보내기 전에
    400 `unsupported-parameter`입니다. LiteLLM 501(기능 미지원)도 장애 알림 없이 400으로 돌려줍니다.
- 평가 경로(#63)
  - `GATEWAY_EXTERNAL_LOG`(파일 경로)가 있을 때만 외부 모델로 실제 보낸 본문(가림 뒤)을
    `contracts/events/external-request.schema.json` 형식으로 씁니다. 로컬 요청, 정책으로 막힌 요청, 연결 전에 실패한 요청은 쓰지 않습니다.
  - 외부 요청 기록에는 `usage`(prompt·completion 토큰)와 `costUsd`(LiteLLM `x-litellm-response-cost` 머리글)를 채웁니다.
    스트림은 머리글 시점에 비용을 몰라 `costUsd`가 null이고, usage는 마지막 조각(`stream_options.include_usage`)에서 읽습니다.
  - 평가 조건(`contracts/eval/conditions.md`)은 대화를 만들 때 정해지고, 같은 `cid`의 출구 호출에 장치를 켜고 끕니다.
    `no_guard`는 가림·기밀 판정·로컬 강제를 모두 끄고, `baseline_tools`는 기밀 판정·로컬 강제를 끄고 가림은 Presidio
    기성 인식기 기본값(spaCy 개체 인식 제외, 한국 인식기 끔)만 씁니다. 두 조건의 위임 토큰은 공용 계정 범위(사람 전용을 뺀 모든
    scope, 팩의 모든 문서 태그)입니다. 나머지 조건은 운영(full)과 같습니다.
  - `POST /api/conversations`의 `X-Eval-Condition`은 `GATEWAY_EVAL_MODE=1`일 때만 받고(아니면 400), 그 대화의 agent `/run`에
    `condition`으로 넘깁니다(`/resume`에는 넘기지 않음).
  - `POST /v1/embeddings`: 로컬 별칭(`local-embed` → Ollama `bge-m3`, 1024차원)만 받습니다. 외부 별칭은 403입니다.
  - `reasoning_effort`는 그대로 넘깁니다. LiteLLM 1.108.1은 Ollama에 `none`이면 `think: false`, `low`·`high`면 `think: true`로
    바꿔 보냅니다(단계는 구분되지 않음). Ollama 전용 `think`는 외부로 보낼 때 뺍니다(Anthropic이 400으로 거절함).
- 외부로 나가는 요청의 기밀 판정과 가림(로컬 모델로 가는 요청은 가리지 않습니다)
  - 사내 용어 사전(`gateway/confidential.py`): 팩의 `glossary.yaml`(#62)에서 용어를 읽어, 용어의 `action`이
    `block`이면 403 `confidential`, `local_only`면 로컬 별칭으로 돌립니다. 파일이 없으면 판정하지 않습니다.
    기록에는 용어 자체를 남기지 않고 개수만 남깁니다.
  - 한국어 개인정보 가림(`gateway/pii.py`): Presidio(2.2.366)에 정규식 인식기만 올립니다. spaCy 언어 모델은 쓰지 않고
    토큰만 나누는 빈 파이프라인을 씁니다. 주민등록번호(생년월일 확인, 검증 숫자가 맞으면 확신), 전화번호(휴대폰·지역번호·+82),
    계좌번호(앞 15글자 안에 "계좌·은행·입금" 같은 문맥 낱말이 있어야 함), 사업자등록번호(검증 숫자), 운전면허번호, 여권번호,
    이메일, 카드번호(Luhn)를 `[전화번호]`처럼 바꿉니다.
  - 가린 개수는 감사 이벤트 `llm.redacted`(개체 종류별 개수)와 `llm.request`의 `model.redactions`에 남고,
    가림 전 원문은 `egress.jsonl`에만 남습니다.
  - 규칙이 못 잡는 형태: 사람 이름, 주소, 한글로 쓴 숫자("공일공"), 숫자 사이에 낯선 구분자를 넣은 것, 문맥 낱말 없는 계좌번호.
    이런 것은 장치 쪽 규칙을 늘리지 않고 평가에서 따로 잽니다.
- 채팅 화면(`gateway/chat.py`): `GET /api/agents`(부를 수 있는 에이전트), `GET·POST /api/conversations`,
  `GET /api/conversations/{id}`(화면 복원용 이벤트 포함), `POST /api/conversations/{id}/messages`(SSE),
  `POST /api/execution-approvals/{id}`(SSE)
  - 첫 메시지에서 agent `/route`로 에이전트를 한 번만 고릅니다(직원이 골랐으면 `explicit`). 요청자가 부를 수 없는
    에이전트면 `blocked`(`agent_not_callable`)입니다.
  - 메시지마다 위임 토큰을 새로 발급해 agent `/run`에 `X-Delegation-Token` 헤더로만 넘기고, RunState를 ChatEvent
    (`route`, `action`, `message`, `citations`, `approval_required`, `blocked`, `error`, 마지막 `done`)로 바꿔 보냅니다.
  - 실행 승인을 기다리는 동안 새 메시지는 409입니다. 승인은 요청자 본인만(403), 한 번만(409), 10분 안에 결정합니다.
    결정은 agent `/resume`으로 넘깁니다.
  - agent가 답하지 않으면 `error`(`retryable: true`)를 보내고 대화는 그대로 둡니다.
  - `message`·`done`의 `model`(name, location): 그 차례에 출구가 위임 토큰의 `cid`로 실제 보낸 모델입니다. 한 번이라도
    외부로 나갔으면 `external`, 아니면 마지막 로컬 별칭입니다. 모델을 쓰지 않은 차례에는 넣지 않습니다.
  - 감사 이벤트: `auth.delegation_token_issued`(jti), `execution_approval.requested`, `execution_approval.decided`
  - 대화와 승인은 프로세스 메모리에 둡니다(1단계). gateway를 다시 띄우면 사라집니다.
- 사람 화면 경로(`gateway/relay.py`): `/api/inbox`, `/api/inbox/{id}`, `/api/inbox/{id}/approve|reject`,
  `/api/delegations`(조회·등록, `?dryRun=true` 미리보기), `/api/delegations/{id}/revoke`, `/api/actions/{id}/undo`,
  `/api/notifications`, `/api/employees`, `/api/approval-forms`. 직원 JWT와 `Idempotency-Key`를 그대로 erp에 넘기고 erp 응답(오류 포함)을 그대로 돌려줍니다.
  읽기에는 요청자·원 결재자·양식·위임자·대리인 이름과 결재선 단계의 `approverName`·`actedByName`을 붙이고, 대결로 들어온 결재 건에는 `viaDelegation`을 채웁니다.
- 감사 조회 `GET /api/audit-events`(`gateway/audit_query.py`, erp `auditor` 역할만): erp `GET /audit-events`,
  gateway 자기 `audit.jsonl`, `AUDIT_EVENT_FILES`(쉼표로 구분한 경로나 glob, agent·MCP·rag가 쓰는 JSON Lines)를 시각 순으로
  합칩니다. `eventId`가 같으면 한 번만 넣습니다. 필터는 `conversationId`, `actorId`, `agentId`, `kind`, `since`·`until`
  (시간대 오프셋 필요)이고, `cursor`는 마지막 이벤트의 (시각, eventId)입니다. erp는 한 번에 최근 500건까지만 줍니다.
- 토큰 위생: 모든 로그 레코드에서 JWT 모양과 `Bearer <값>`을 가립니다(`gateway/redact.py`). 발급 기록은 `jti`만 남깁니다.

## 실행

```bash
source ../scripts/env.sh 2
bash ../scripts/dev-keys.sh                       # 위임 토큰 키(커밋하지 않음)
(cd ../contracts && DELEGATION_TOKEN_PUBLIC_KEY=infra/dev-keys/delegation-es256.pub.pem \
  uv run uvicorn fakes.erp.app:app --port $PORT_FAKE_ERP) &
export LITELLM_MASTER_KEY=sk-...                   # LiteLLM 프록시와 gateway가 같은 값을 씁니다
(cd .. && OLLAMA_BASE_URL=http://localhost:11434 \
  uvx --python 3.12 --from 'litellm[proxy]==1.108.1' litellm --config gateway/litellm/config.yaml --port $PORT_LITELLM) &
ERP_BASE_URL=http://localhost:$PORT_FAKE_ERP/api/v1 \
LITELLM_BASE_URL=http://localhost:$PORT_LITELLM \
DELEGATION_TOKEN_PRIVATE_KEY=infra/dev-keys/delegation-es256.pem \
  uv run uvicorn --factory gateway.main:create_app --port $PORT_GATEWAY
```

환경 변수: `ERP_BASE_URL`, `PACK_DIR`(기본 `packs/manufacturing`), `CONTRACTS_DIR`(기본 `contracts`),
`DELEGATION_TOKEN_PRIVATE_KEY`(없으면 임시 키를 만들고 경고를 남깁니다), `LITELLM_BASE_URL`(기본 `http://localhost:4000`),
`LITELLM_MASTER_KEY`, `LITELLM_CONFIG`, `LLM_TIMEOUT_SECONDS`, `GATEWAY_AUDIT_DIR`, `ALERT_WEBHOOK_URL`, `AUDIT_EVENT_FILES`, `AGENT_BASE_URL`(기본 `http://localhost:8020`),
`AGENT_TIMEOUT_SECONDS`(기본 120), `GATEWAY_EXTERNAL_LOG`, `GATEWAY_EVAL_MODE`.
상대 경로는 저장소 루트 기준입니다. LiteLLM은 1.108.1로 고정합니다(배포 뒤 2주가 지난 판).

## 시험

```bash
uv sync && uv run pytest -q
```

시험은 `contracts/fakes/erp`를 프로세스 안에서 띄워 erp 자리에 둡니다. 발급한 토큰을 가짜 erp가 받아들이는지,
범위 밖 scope와 사람 화면 전용 API를 거절하는지도 봅니다.
