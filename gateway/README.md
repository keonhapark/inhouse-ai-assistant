# gateway

web이 부르는 유일한 서버입니다. 계약은 `contracts/openapi/gateway.yaml`(서버 기준 경로 `/api`)입니다.

지금 있는 것(1단계 #8, #9, #10, #11 일부):

- `GET /health`, `GET /api/health`
- `GET /api/.well-known/jwks.json`: 위임 토큰 검증용 공개 키. `kid`는 RFC 7638 지문입니다.
- `POST /api/auth/login`, `GET /api/me`: erp에 그대로 넘기고 상태 코드와 본문을 그대로 돌려줍니다.
- 위임 토큰 발급(`gateway/delegation.py`): 대화마다 ES256, 10분. 클레임은 `contracts/auth/delegation-token.schema.json`입니다.
  - `scopes`: 라우팅된 에이전트 도구(`agents.yaml`의 `tools`)의 `required_scope`에서 사람 화면 전용 scope를 뺀 것입니다.
    직원 JWT는 erp에서 모든 scope를 가지므로, 요청자 쪽 제한은 erp가 "토큰 주인의 권한 ∩ 토큰 scopes"로 다시 봅니다.
  - `doc_scopes`: erp `/me/access-tags` ∩ 에이전트 `doc_scopes`
  - 에이전트 `callable_by`에 맞지 않는 요청자는 403입니다.
- LLM 출구 `POST /v1/chat/completions`(OpenAI 호환, `/api` 밖): 정책을 확인한 뒤 LiteLLM 프록시로 넘깁니다(`gateway/egress.py`).
  - `model`은 `litellm/config.yaml`의 별칭만 받습니다: `local`(Ollama `qwen3.5:9b`, 문맥 8192), `external`(Claude Haiku).
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
- 외부로 나가는 요청의 기밀 판정과 가림(로컬 모델로 가는 요청은 가리지 않습니다)
  - 사내 용어 사전(`gateway/confidential.py`): 팩의 `glossary.yaml`(형식 요청 #43)에서 용어를 읽어, 용어의 `action`이
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
- 사람 화면 경로(`gateway/relay.py`): `/api/inbox`, `/api/inbox/{id}`, `/api/inbox/{id}/approve|reject`,
  `/api/delegations`(조회·등록, `?dryRun=true` 미리보기), `/api/delegations/{id}/revoke`, `/api/actions/{id}/undo`,
  `/api/notifications`. 직원 JWT와 `Idempotency-Key`를 그대로 erp에 넘기고 erp 응답(오류 포함)을 그대로 돌려줍니다.
  읽기에는 요청자·원 결재자·양식·위임자·대리인 이름을 붙이고, 대결로 들어온 결재 건에는 `viaDelegation`을 채웁니다.
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
`LITELLM_MASTER_KEY`, `LITELLM_CONFIG`, `LLM_TIMEOUT_SECONDS`, `GATEWAY_AUDIT_DIR`, `ALERT_WEBHOOK_URL`, `AUDIT_EVENT_FILES`.
상대 경로는 저장소 루트 기준입니다. LiteLLM은 1.108.1로 고정합니다(배포 뒤 2주가 지난 판).

## 시험

```bash
uv sync && uv run pytest -q
```

시험은 `contracts/fakes/erp`를 프로세스 안에서 띄워 erp 자리에 둡니다. 발급한 토큰을 가짜 erp가 받아들이는지,
범위 밖 scope와 사람 화면 전용 API를 거절하는지도 봅니다.
