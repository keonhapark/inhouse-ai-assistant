# gateway

web이 부르는 유일한 서버입니다. 계약은 `contracts/openapi/gateway.yaml`(서버 기준 경로 `/api`)입니다.

지금 있는 것(1단계 #8~#11):

- `GET /health`, `GET /api/health`
- `GET /api/.well-known/jwks.json`: 위임 토큰 검증용 공개 키. `kid`는 RFC 7638 지문입니다.
- `POST /api/auth/login`, `GET /api/me`: erp에 그대로 넘기고 상태 코드와 본문을 그대로 돌려줍니다.
- 위임 토큰 발급(`gateway/delegation.py`): 대화마다 ES256, 10분. 클레임은 `contracts/auth/delegation-token.schema.json`입니다. `aud`는 erp·rag·mcp·incident(#352)입니다.
  - `scopes`: 라우팅된 에이전트 도구(`agents.yaml`의 `tools`)의 `required_scope`에서 사람 화면 전용 scope를 뺀 것입니다.
    직원 JWT는 erp에서 모든 scope를 가지므로, 요청자 쪽 제한은 erp가 "토큰 주인의 권한 ∩ 토큰 scopes"로 다시 봅니다.
  - `doc_scopes`: erp `/me/access-tags` ∩ 에이전트 `doc_scopes`
  - 에이전트 `callable_by`에 맞지 않는 요청자는 403입니다.
- LLM 출구 `POST /v1/chat/completions`(OpenAI 호환, `/api` 밖): 정책을 확인한 뒤 LiteLLM 프록시로 넘깁니다(`gateway/egress.py`).
  - `model`은 `litellm/config.yaml`의 별칭만 받습니다: `local`(Ollama `qwen3.5:9b`, 문맥 8192), `external`(Claude Haiku 5.5, `claude-haiku-5-5`).
    `local-gguf`(같은 Qwen3.5-9B의 GGUF Q4_K_M 판, llama.cpp 실행기, digest `56671c2ab938`)는 구조화 출력(`response_format`)이 됩니다.
    `local`(safetensors nvfp4, MLX 실행기, digest `d63f830f28d5`)은 되지 않아 400입니다(#205). 폴백·로컬 내림은 `local`을 씁니다.
    별칭마다 `model_info.location`이 있고, gateway는 이것으로 로컬·외부를 가릅니다.
  - 평가 전용 별칭(모델 교체 회귀 #107·#346, 기본 경로에서는 쓰지 않음): `external-sonnet`(Claude Sonnet 5.5,
    `claude-sonnet-5-5`, $2 / $10 per MTok, 기본값이 아닌 `temperature`·`top_p`는 뺌)과 `local-exaone`(EXAONE 4.0 1.2B 공식
    GGUF Q4_K_M, Ollama가 `hf.co/LGAI-EXAONE/EXAONE-4.0-1.2B-GGUF:Q4_K_M`으로 받음, 812MB). EXAONE 라이선스는
    "EXAONE AI Model License Agreement 1.2 - NC"(비상업, 연구·교육 사용)라 평가 측정에만 쓰고 가중치는 커밋하지 않습니다.
    평가 대화는 `POST /api/conversations`의 `X-Eval-Model-Override`(평가 모드에서만)로 그 대화의 출구 별칭을 바꿔 끼웁니다:
    `local=local-exaone`은 로컬 업무 별칭(`local`·`local-gguf`, 기밀 판정·비용 상한·외부 장애 폴백의 로컬 포함),
    `external=external-sonnet`은 `external`. 같은 위치의 별칭으로만 바꿔 모델 정책·가림·기밀 판정은 그대로이고, 이미지
    (`local-vision`)와 토큰 없는 호출(입구 라우터)은 바꾸지 않습니다. 감사 detail에 `평가 별칭 바꿔 끼움: A 대신 B`를 남깁니다.
  - `X-Delegation-Token`이 있으면 서명·만료를 확인하고 `agt`의 `model_policy`를 따릅니다. `local_only` 에이전트와
    토큰 없는 호출은 `external`을 쓰면 403 `model-policy`이고, 밖으로 아무것도 나가지 않습니다.
  - 팩 단위 외부 LLM 금지(#384): `pack.yaml`에 `model_policy_override: local_only`가 있으면(망분리 흉내) 모든 에이전트의
    모델 정책을 local_only로 보고(`/api/agents`·`/api/agent-registry`에도 그렇게 나옴), 출구는 평가 조건(`no_guard`·
    `baseline_tools` 포함)·평가 별칭 바꿔 끼우기보다 먼저 외부 별칭을 막습니다. 위임 토큰 호출은 로컬 별칭(평가 대화면 바꿔 끼운
    로컬)으로 돌리고 감사 detail에 `팩 외부 LLM 금지: A 대신 B`를 남깁니다. 에이전트가 팩 항목을 몰라 외부를 요청해도 대화가
    깨지지 않게 하려는 것입니다. 토큰 없는 외부 호출(도구 호출 측정 등)은 측정이 몰래 로컬로 바뀌지 않게 403입니다.
    예외: `GATEWAY_EVAL_TOOLCALL=1`인 스택(도구 호출 측정 #103 전용)에서는 토큰 없는 외부 호출도 가림·기밀 판정·외부 기록을
    거쳐 보내고 감사 detail에 `purpose=eval-toolcall`을 적습니다. `GATEWAY_EVAL_MODE`와 따로 둡니다(#294): 정상·확인 셋
    실행에서 열리면 대화 밖 외부 전송이 평가 판정에서 빠지기 때문입니다.
  - 토큰 헤더는 LiteLLM으로 넘기지 않고, 본문의 토큰 모양 문자열도 가린 뒤 보냅니다.
  - 기록(`GATEWAY_AUDIT_DIR`, 기본 `gateway/var/`, 커밋하지 않음): `audit.jsonl`에 감사 이벤트 `llm.request`
    (모델, 외부 전송 여부, 결과. 위임 토큰이 있으면 `actor.employeeId`·`agentId`는 토큰의 `sub`·`agt`),
    `egress.jsonl`에 외부로 나간 요청의 가림 뒤 본문, 가린 자리(종류·위치), 응답, 사용량·비용.
    가림 전 원문은 저장하지 않습니다(#211, `/ops/egress` 계약). 응답 본문이 들어 있어 접근을 제한해야 하는 파일입니다.
  - 감사 이벤트의 `actor.channel`(#338)은 요청이 들어온 입구입니다. 대화·실행 승인·위임 토큰 발급·gateway가 남기는 라우팅은
    직원 JWT면 `web`, 슬랙 로그인 토큰(`amr` slack)이면 `slack`, 슬랙 로그인 기록은 `slack`, 출구(`llm.request`·
    `llm.redacted`)는 위임 토큰이 있으면 `agent`이고 토큰 없는 호출은 입구를 몰라 넣지 않습니다.
  - 토큰 없는 호출의 `llm.request`는 `actor.employeeId`·`agentId`가 null입니다(#276). 출구는 위임 토큰으로만 요청자를
    알기 때문입니다. 지금 이런 호출은 agent 입구 라우터의 분류 호출(에이전트를 고르기 전이라 토큰이 없음)과 도구 호출 측정
    스택(`GATEWAY_EVAL_TOOLCALL=1`)의 측정 호출(`purpose=eval-toolcall`)입니다. rag 질의 임베딩은 #191 뒤로 토큰을 붙입니다.
    2026-11-21 실제 스택 기록에서 토큰이 있는 호출 537건은 모두 채워져 있었고, null 272건은 모두 토큰 없는 호출이었습니다
    (그중 rag 질의 임베딩 101건은 #191 전 이미지의 기록).
  - 시간 제한(`LLM_TIMEOUT_SECONDS`, 기본 60초) 초과는 504 `llm-timeout`, 연결 실패는 502 `llm-unavailable`,
    LiteLLM 5xx는 502 `llm-upstream-error`이고, 모두 실패 알림(오류 로그, `ALERT_WEBHOOK_URL`이 있으면 웹훅)을 보냅니다.
  - 비용 상한(`gateway/budgets.py`, 팩 선택 파일 `budgets.yaml`, #155): 외부 응답 비용(LiteLLM `x-litellm-response-cost`,
    스트림은 별칭 단가 `model_info.input_cost_per_token`·`output_cost_per_token`과 usage로 계산)을 기간(day|month)마다 에이전트와
    부서(요청자 소속과 상위 부서)에 더해 `GATEWAY_AUDIT_DIR/budget.json`에 둡니다. 상한에 닿은 에이전트·부서의 다음 외부 요청은
    로컬로 내리고 감사 detail에 `비용 상한 초과(...)`를 적습니다. 진행 중인 요청은 끝까지 갑니다. 로컬 강제를 끄는 평가 조건에서는 끕니다.
  - 외부 별칭이 위 세 가지로 실패하면 같은 요청을 로컬 별칭으로 한 번 다시 보냅니다(로컬 폴백). 외부 실패는 그대로 알림·감사(error)를
    남기고, 로컬 호출의 감사 이벤트 detail에 `외부 장애(<코드>)로 로컬 폴백`을 적습니다. 로컬이 지원하지 않는 `response_format`
    요청, 미지원(400), 정책 거절, 로컬 별칭 자체의 실패는 폴백하지 않습니다. 스트림은 흘려보내기 전에 실패한 경우만 폴백합니다.
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
  - 외부 요청 기록(`GATEWAY_EXTERNAL_LOG`)의 `model`은 별칭이 아니라 실제 모델 이름(LiteLLM 설정 `litellm_params.model`,
    예: `anthropic/claude-haiku-5-5`)입니다(#203). 응답 헤더 `X-Egress-Model`은 별칭이고, 운영 기록 `egress.jsonl`에는 별칭(`model`)과
    실제 이름(`providerModel`)을 둘 다 둡니다.
  - 외부 요청 기록에는 `usage`(prompt·completion 토큰)와 `costUsd`(LiteLLM `x-litellm-response-cost` 머리글)를 채웁니다.
    스트림은 머리글 시점에 비용을 몰라 `costUsd`가 null이고, usage는 마지막 조각(`stream_options.include_usage`)에서 읽습니다.
  - 평가 조건(`contracts/eval/conditions.md`)은 대화를 만들 때 정해지고, 같은 `cid`의 출구 호출에 장치를 켜고 끕니다.
    `no_guard`는 가림·기밀 판정·로컬 강제를 모두 끄고, `baseline_tools`는 기밀 판정·로컬 강제를 끄고 가림은 Presidio
    기성 인식기 기본값(spaCy 개체 인식 제외, 한국 인식기 끔)만 씁니다. 두 조건의 위임 토큰은 공용 계정 범위(사람 전용을 뺀 모든
    scope, 팩의 모든 문서 태그)입니다. 나머지 조건은 운영(full)과 같습니다.
  - `POST /api/conversations`의 `X-Eval-Condition`은 `GATEWAY_EVAL_MODE=1`일 때만 받고(아니면 400), 그 대화의 agent `/run`에
    `condition`으로 넘깁니다(`/resume`에는 넘기지 않음).
  - 메시지의 `attachments`(이미지, 최대 3장, #288)는 LLM 출구 이미지 입력(#261)과 같은 규칙(jpeg·png data URL, 한 장 5MB,
    413·415·422)으로 확인한 뒤 그 턴의 agent `/run`에 그대로 넘깁니다. 라우터(`/route`)에는 넘기지 않고, 대화 기록에도 남기지
    않습니다. agent가 이미지를 읽을 때는 출구가 `local-vision`으로만 보내고 감사에 형식·크기·SHA-256을 남깁니다.
  - `POST /v1/embeddings`: 로컬 별칭(`local-embed` → Ollama `bge-m3`, 1024차원)만 받습니다. 외부 별칭은 403입니다.
  - `reasoning_effort`는 그대로 넘깁니다. LiteLLM 1.108.1은 Ollama에 `none`이면 `think: false`, `low`·`high`면 `think: true`로
    바꿔 보냅니다(단계는 구분되지 않음). Ollama 전용 `think`는 외부로 보낼 때 뺍니다(Anthropic이 400으로 거절함).
- 외부로 나가는 요청의 기밀 판정과 가림(로컬 모델로 가는 요청은 가리지 않습니다)
  - 사내 용어 사전(`gateway/confidential.py`): 팩의 `glossary.yaml`(#62)에서 용어를 읽어, 용어의 `action`이
    `block`이면 403 `confidential`, `local_only`면 로컬 별칭으로 돌립니다. 파일이 없으면 판정하지 않습니다.
    기록에는 용어 자체를 남기지 않고 개수만 남깁니다.
  - 업무 주제(`glossary.yaml`의 `topics`, #304): 정규식으로 대화 내용(system이 아닌 메시지의 content와 도구 호출 인자)만
    봅니다. 시스템 프롬프트와 도구 정의는 보지 않습니다(에이전트·도구 설명에 주제어가 있어도 걸리지 않게). 제조 팩의
    `hr-attendance`는 휴가·병가·대결·급여 같은 인사·근태 정보를 로컬로 돌립니다. 입구 라우터가 인사 요청을 외부 허용
    에이전트로 잘못 보내도(#86 사고, #308 로컬 장애 때 폴백) 출구에서 막는 두 번째 방어선입니다. 감사 detail에는
    `업무 주제 hr-attendance: 로컬 모델로 돌림`처럼 주제 id만 남깁니다. 용어 사전과 같이 `no_guard`·`baseline_tools`
    평가 조건에서는 끕니다.
  - 한국어 개인정보 가림(`gateway/pii.py`): Presidio(2.2.366)에 정규식 인식기만 올립니다. spaCy 언어 모델은 쓰지 않고
    토큰만 나누는 빈 파이프라인을 씁니다. 주민등록번호(생년월일 확인, 검증 숫자가 맞으면 확신), 전화번호(휴대폰·지역번호·+82),
    계좌번호(앞 15글자 안에 "계좌·은행·입금" 같은 문맥 낱말이 있어야 함), 사업자등록번호(검증 숫자), 운전면허번호, 여권번호,
    이메일, 카드번호(Luhn)를 `[전화번호]`처럼 바꿉니다.
  - 가린 개수는 감사 이벤트 `llm.redacted`(개체 종류별 개수)와 `llm.request`의 `model.redactions`에 남고,
    가린 자리는 `egress.jsonl`의 `redactionSpans`에 남고, 가림 전 원문은 어디에도 저장하지 않습니다.
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
- 관리자 콘솔 `GET /api/ops/egress`(`gateway/ops.py`, auditor만): 외부로 실제 보낸 요청을 최근 것부터 계약의 `EgressRecord`로
  돌려줍니다. `messages`는 가림 뒤 본문(부분 배열 content는 텍스트 부분을 줄바꿈으로 이어 붙임)이고, `redactions`의 위치는
  화면(JavaScript)과 맞도록 UTF-16 단위입니다. content 밖(도구 호출 인자)에서 가린 것은 위치를 돌려주지 않습니다.
- 관리자 콘솔 `GET /api/ops/metrics`(auditor만, `since` 없으면 `until` 24시간 전): 감사 이벤트(gateway 기록과 `AUDIT_EVENT_FILES`)와
  운영 기록에서 에이전트별 호출 수(`route.decided`), 정책 차단(`tool.blocked`·`rag.access_denied`·출구 거절·부를 수 없는 에이전트를
  ChatEvent `blocked.code`로 나눔), 로컬·외부 요청 수, 외부 비용(`costUsd` 합, 모르면 `unpricedRequests`), 라우팅 방식별 수,
  비용 상한 사용량(지금 누적 기간)을 셉니다. 직원이 고른 대화(`explicit`)와 부를 수 없는 에이전트로 간 라우팅은 gateway가
  `route.decided`를 남깁니다.
- 감사 조회 `GET /api/audit-events`(`gateway/audit_query.py`, erp `auditor` 역할만): erp `GET /audit-events`,
  gateway 자기 `audit.jsonl`, `AUDIT_EVENT_FILES`(쉼표로 구분한 경로나 glob, agent·MCP·rag가 쓰는 JSON Lines)를 시각 순으로
  합칩니다. `eventId`가 같으면 한 번만 넣습니다. 필터는 `conversationId`, `actorId`, `agentId`, `kind`, `since`·`until`
  (시간대 오프셋 필요)이고, `cursor`는 마지막 이벤트의 (시각, eventId)입니다. `order=desc`면 최근 것부터 주고 `cursor`는
  더 오래된 쪽으로 이어집니다(#276, 기본 asc). erp는 한 번에 최근 500건까지만 줍니다.
- 평가 보고서 조회 `GET /api/eval/reports`, `GET /api/eval/reports/{reportId}`(`gateway/eval_reports.py`, #332, auditor만):
  `GATEWAY_EVAL_REPORTS_DIR`(기본 `eval/reports`, compose는 `/eval-reports`에 읽기 전용 마운트)의 `*.json` 보고서를 읽기만
  합니다. 목록은 본문 `meta`에서 뽑아 최근 것부터 주고, `title`은 같은 이름 `.md`의 첫 제목, `sets`는 회차에 나온 셋,
  `hasSummary`는 `summary`가 있는지입니다. 읽지 못하는 파일은 목록에서 빼고 로그에 남깁니다. `reportId`는 계약 pattern만
  받고, 파일 경로를 풀어(심볼릭 링크 포함) 폴더 안일 때만 읽으며 아니면 404입니다.
- 팩 단계(#170): `pack.yaml`의 `stage`가 기준이고 `GATEWAY_PACK_STAGE`는 덮어쓰기만 합니다. 그 단계 이하 에이전트만
  등록부에 실어, `/api/agents`에 보이지 않는 에이전트는 대화를 만들 수 없고(403) 위임 토큰도 발급하지 않습니다(404).
- 사람용 경로(`/api/*`의 로그인 뒤 경로)는 직원 JWT만 받습니다. Bearer 값이 위임 토큰(`iss: gateway` 또는 `agt` 클레임)이면
  403 `delegation-token-not-allowed`입니다(#159). 위임 토큰은 agent → MCP → erp와 LLM 출구(`X-Delegation-Token`)에만 씁니다.
- 슬랙 로그인 `POST /api/auth/slack`(`gateway/slack_login.py`, #273): 슬랙 브리지만 부릅니다. 헤더 `X-Slack-Bridge-Secret`이
  `SLACK_BRIDGE_SECRET`과 맞고(상수 시간 비교, 틀리면 401) `slackUserId`가 매핑 파일(`SLACK_USERS_FILE`, 기본
  `infra/slack/slack-users.json`, 커밋하지 않음. 형식은 `infra/slack/slack-users.example.json`)에 있으면 erp
  `POST /auth/service-login`(`ERP_SERVICE_LOGIN_SECRET`)으로 받은 직원 JWT(15분, `amr: [slack]`)를 돌려줍니다. 매핑에 없거나
  매핑된 직원이 erp에 없으면 403, `SLACK_BRIDGE_SECRET`이 없으면 404, erp가 서비스 비밀값을 거절하면 gateway 설정 문제로 보고 502입니다.
  감사 `auth.login`에 `출처 slack`과 결과를 남기고 비밀값·토큰은 남기지 않습니다. `ERP_SERVICE_LOGIN_SECRET`이 없거나 비면
  erp를 부르지 않고 502입니다. 이 토큰(`amr`에 slack, 배열이든 문자열이든)은 허용 목록(`SLACK_ALLOWED`)의 경로만 부를 수
  있습니다: 내 정보, 알림, 대화 만들기·조회·메시지, 실행 승인, 되돌리기. 그 밖(대결, 결재함, 감사, 운영 등)은 `relay.bearer`가
  403 `service-login-not-allowed`로 막습니다. 막을 경로 대신 허용할 경로를 적어, 새 사람 화면 경로가 생겨도 슬랙 토큰에는
  닫혀 있습니다(브리지 비밀값이 새도 팀장 슬랙 ID로 대결을 등록해 승인 권한을 넘기는 우회를 막음).
  요청 횟수 제한(#331): 슬랙 사용자 ID별(`SLACK_LOGIN_PER_USER_PER_MINUTE`, 기본 10)과 경로 전체(`SLACK_LOGIN_PER_MINUTE`,
  기본 60, 비밀값이 틀린 요청 포함) 분당 상한을 넘으면 429 `rate-limited`와 `Retry-After`(초)입니다. 최근 60초 창을 프로세스
  메모리에서 세므로 gateway를 여러 개 띄우면 개수만큼 늘어납니다. 429 감사는 같은 키에 60초마다 한 번만 남깁니다.
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
`AGENT_TIMEOUT_SECONDS`(기본 120), `GATEWAY_EXTERNAL_LOG`, `GATEWAY_EVAL_MODE`, `GATEWAY_EVAL_TOOLCALL`, `GATEWAY_PACK_STAGE`,
`SLACK_BRIDGE_SECRET`, `SLACK_USERS_FILE`, `ERP_SERVICE_LOGIN_SECRET`, `SLACK_LOGIN_PER_USER_PER_MINUTE`, `SLACK_LOGIN_PER_MINUTE`, `GATEWAY_EVAL_REPORTS_DIR`.
상대 경로는 저장소 루트 기준입니다. LiteLLM은 1.108.1로 고정합니다(배포 뒤 2주가 지난 판).

## 시험

```bash
uv sync && uv run pytest -q
```

시험은 `contracts/fakes/erp`를 프로세스 안에서 띄워 erp 자리에 둡니다. 발급한 토큰을 가짜 erp가 받아들이는지,
범위 밖 scope와 사람 화면 전용 API를 거절하는지도 봅니다.
