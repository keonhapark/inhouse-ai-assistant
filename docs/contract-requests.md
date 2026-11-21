
| 2026-11-21 | erp | #291 | erp `POST /auth/service-login`(헤더 `X-Service-Login-Secret`, 본문 `{employeeId}`, 15분 직원 JWT `amr: [slack]`, 401·404·422), ProblemCode `service-login-not-allowed`(사람 전용 기능 403) | #273 슬랙 로그인 A안 | 직접 PR |
모듈 세션이 계약(`contracts/`)이나 팩(`packs/`)을 바꿔야 할 때 한 줄 적고 `contract` 라벨 이슈를 엽니다. 프로젝트 리드가 `contract/*` PR로 반영하고 결과를 적습니다.

| 날짜 | 요청 모듈 | 이슈 | 바꿀 것 | 이유 | 결과 |
|---|---|---|---|---|---|
| 2026-11-20 | rag | #37 | `packs/manufacturing/docs.yaml` 공개 규정 3건의 정식 제목·출처 주소·status ready, 생성 문서 5건 status ready | #16에서 법제처 원문을 확인하고 고정본을 만듦 | 반영 |
| 2026-11-20 | gateway | #43 | 팩 선택 파일 `glossary.yaml`(사내 용어 사전: term, aliases, level, action local_only·block, reason) 형식과 제조 팩 용어 | #10 기밀 판정. 코어에 업종 용어를 둘 수 없어 팩에서 읽음 | 반영 |
| 2026-11-20 | rag | - | rag.yaml `/answer` 502·503 | gateway 출구 실패를 구분 | 반영 |
| 2026-11-20 | eval | - | `events/external-request.schema.json`(GATEWAY_EXTERNAL_LOG) | 외부 요청 본문에서 표지 판정 | 반영, gateway 구현 이슈 |
| 2026-11-20 | eval | - | scenario `expect.markerSources`, `eval/markers.schema.json`(RAG_MARKERS_FILE), `eval/injected-docs.schema.json`(RAG_EXTRA_DOCS) | 표지 대상 지정, 표지·주입 문서 심기 | 반영, rag 구현 이슈 |
| 2026-11-20 | eval | - | gateway `X-Eval-Condition` 헤더(GATEWAY_EVAL_MODE=1) | 조건별 실행 | 반영, gateway 구현 이슈 |
| 2026-11-20 | eval | - | erp `POST /_eval/reset`(ERP_EVAL_RESET=1), 가짜 erp 구현 | 회차 사이 초기화 | 반영, erp 구현 이슈 |
| 2026-11-20 | web | #67 | gateway `GET /employees`, `GET /approval-forms`, `InboxItem.steps[]` 이름 | 대결 설정·결재선 화면 | 반영 |
| 2026-11-20 | gateway | - | `X-Eval-Condition`은 /run에만 넘김(설명 정정) | agent.yaml /resume에 condition 없음 | 반영 |
| 2026-11-20 | agent | - | MCP 요청 `_meta`(dryRun, idempotencyKey, trustLevel)를 `contracts/mcp/README.md`에 적음 | LLM이 고를 수 없는 값 | 반영 |
| 2026-11-20 | agent | #15 | agent `POST /baseline/slots`(rule·llm, 실행 없이 도구·인자 반환) | 기준선과 LLM 경로를 같은 입력으로 비교 | 반영 |
| 2026-11-20 | eval | - | 조건별 장치 구성 `contracts/eval/conditions.md`, external-request `usage`·`costUsd` | gateway 장치가 조건에 따라 켜지고 꺼지지 않음, 비용 상한 | 반영, gateway·agent 구현 이슈 |
| 2026-11-20 | 리드 | #145 | tools.json `expense_request`·`purchase_request`, 팩 재무·구매자재 에이전트 | 2단계 부서 에이전트 | 반영. IT 티켓 도구는 erp 티켓 API가 필요해 장애 분석 epic #101로 |
| 2026-11-20 | rag | #148 | rag.yaml `asOf`, `Passage`·`Citation` `edition`, `Answer` `revisions`, `DELETE /documents/{docId}`(RAG_ADMIN_TOKEN), audit `rag.document_purged` | #142 판 메타·충돌 표시, 개인정보 파기 | 승인, 직접 PR |
| 2026-11-20 | rag | #167 | gateway LLM 출구 응답 헤더 `X-Egress-Model`·`X-Egress-Location`(설명), rag.yaml `/search` 502·503 | 실제 쓴 모델·경로 기록, 질의 임베딩 실패가 계약에 없는 500 | 직접 PR, gateway 구현 필요 |
| 2026-11-20 | gateway | #155 | 팩 선택 파일 `budgets.yaml`(period, agents·units별 USD 상한)과 스키마·참조 검사 | #143 비용 상한. 코어에 업종 용어를 둘 수 없어 팩에서 읽음 | contract/gateway-budgets PR |
| 2026-11-20 | agent | #204 | agent.yaml `POST /eval/tool-call`(AGENT_EVAL_MODE=1, 실행 없이 첫 도구 호출), `ToolCallVariant`·`ToolCallResult` | #103 로컬 모델 도구 호출 측정(변형·모델별 같은 입력) | contract/agent-eval-tool-call PR. 문법 제약용 로컬 별칭은 #205(gateway) |
| 2026-11-20 | web | #210 | gateway `GET /ops/metrics`(에이전트별 호출·정책 차단·외부/로컬·외부 비용·라우팅 결과·비용 상한 사용량), `GET /ops/egress`(외부 전송 기록, 가림 뒤 본문과 가린 자리만) | #105 관리자 콘솔(#212) | contract/web-ops PR, gateway 구현 #211 |
| 2026-11-20 | web | #220 | gateway `GET /org/units`(erp 그대로), `GET /agent-registry`(팩 에이전트 전체: 담당 부서·도구와 위험 등급·허용 위험·문서 범위·모델 정책·위험 정책·단계) | #105 조직도·에이전트 등록부 | contract/web-registry PR, gateway 구현 필요 |
| 2026-11-20 | eval | #192 | 시나리오 `executionApprover` 값 `intent`, `expect.approvable`(tool, after) | full·write_blocked 하네스 승인자를 사용자 의도와 맞을 때만 승인하도록(결정 0004 뒤 평가에서 신뢰 등급 장치 효과가 0이 되는 문제) | contract/eval-approver PR |
| 2026-11-20 | erp | #226 | 팩 org.yaml 선택 항목 `erp_roles`(hr, auditor, 없으면 hr_staff·auditor), erp.yaml 역할 설명을 팩 항목으로 | #166 코어에 역할 이름을 두지 않음 | 직접 PR |
| 2026-11-20 | erp | #228 | erp.yaml `ProblemCode`에 `internal`, 머리말에 405(`validation`)·500(`internal`) 한 줄 | #166 구현이 내는 응답이 계약에 없음 | 직접 PR |
| 2026-11-21 | erp | #238 | erp.yaml IT 티켓(`/tickets` 목록·상세·작성·댓글·상태 변경), scope `ticket:read·write·manage`, tools.json `ticket_list·get·create·comment`(stage 2), 팩 `erp_roles.ticket_handler`·`fixtures/tickets.json`(선택) | #99 IT운영 에이전트 | 직접 PR |
| 2026-11-21 | gateway | #263 | gateway LLM 출구 이미지 입력: `image_url`(jpeg·png data URL, 한 장 5MB)은 `local-vision`으로만, 413 `payload-too-large`·415 `unsupported-media-type` | #261 영수증 읽기(#100) | contract/gateway-vision PR |
| 2026-11-21 | erp | #252 | 팩 forms 선택 항목 `amount_product_of`(금액 필드 = 필드들의 곱, 다르면 422 form-validation-failed), 제조 팩 구매 양식 `[quantity, unit_price]` | 합계를 틀리게 적어 고액 확인·결재선을 비켜 감 | 직접 PR |
| 2026-11-21 | gateway | #289 | gateway `GET /audit-events` 선택 파라미터 `order`(asc|desc, 기본 asc) | #276 관리자 콘솔에서 최근 감사 이벤트 보기 | contract/gateway-audit-order PR |
| 2026-11-21 | agent | #286 | agent.yaml `Attachment`, `/run` `attachments`; gateway.yaml 대화 메시지 `attachments`(413·415) | #281 영수증 이미지를 대화로 받아 로컬 비전으로 읽음 | contract/agent-attachments PR. gateway 전달 구현은 gateway 이슈 |
| 2026-11-21 | agent | #309 | agent.yaml `/run` 선택 필드 `routeMethod`(llm·keyword·fallback·explicit) | #308 fallback 대화가 전사 비서 정책(external)으로 외부에 나감. fallback이면 대화 끝까지 로컬 | contract/agent-route-method PR. gateway 전달은 gateway 이슈 |
| 2026-11-21 | gateway | #273 | gateway `POST /auth/slack`(헤더 `X-Slack-Bridge-Secret`, 본문 `{slackUserId}`, 응답 erp `LoginResponse`, 401·403·404), erp `POST /auth/service-login`(#291)을 부름 | #102 슬랙 입구 | contract/gateway-slack PR |
| 2026-11-21 | gateway | #304 | 팩 glossary.yaml 선택 항목 `topics`(id·action·reason·patterns 정규식, 대화 내용만 봄), 제조 팩 hr-attendance | #304 인사 정보 로컬 강제(#308 두 번째 방어선) | contract/gateway-local-topics PR |
| 2026-11-21 | gateway | #331 | gateway `POST /auth/slack` 429 `rate-limited`(`Retry-After`), 슬랙 사용자별·전체 분당 상한 | #331 브리지 비밀값이 새도 토큰을 마음대로 받지 못하게 | contract/gateway-slack-rate-limit PR |
