# 계약 변경 요청

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
