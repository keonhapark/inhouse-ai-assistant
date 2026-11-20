# 끝까지 시험(compose 전체)

1단계 서비스(erp·gateway·agent·rag·litellm·web)를 compose로 모두 띄우고, 사람이 쓰는 경로대로 정상 흐름을 확인합니다. 시험은 `E2E_GATEWAY_URL`·`E2E_ERP_URL`이 있을 때만 돌고, CI의 모듈 시험(`uv run pytest`, `tests/`만)에는 들어가지 않습니다.

## 시험

| 시험 | 확인하는 것 | 모델 호출 |
|---|---|---|
| `test_chat_leave_preview_approve_execute_undo` | 채팅으로 반차 신청 → 인사 에이전트로 라우팅 → (실행 승인이 나오면 미리보기 확인 후 승인) → 실행 → erp에 진행 중 문서 → 되돌리기로 회수 | 있음 |
| `test_policy_question_has_citations` | 규정 질의 답에 근거(citations)가 있음 | 있음 |
| `test_leader_approves_from_inbox` | 팀장 승인함(`/inbox`)에 요청자·양식 이름이 붙고 승인됨 | 없음 |
| `test_delegation_then_proxy_approval` | 팀장이 대결 등록 → 대리인 `delegated` 함에 원 결재자 표시 → 대리 승인 → 결재 단계에 `actedBy`·`onBehalfOf`·`delegationId` | 없음 |

## 실행

```
source scripts/env.sh 5
export LITELLM_MASTER_KEY=sk-<임의 값> ERP_EVAL_RESET=1 GATEWAY_EVAL_MODE=1 GATEWAY_EXTERNAL_LOG=/audit/external.jsonl
docker compose -f infra/compose.yaml -f eval/e2e/compose.eval.yaml --env-file .env --profile full up -d --build --wait

cd eval
set -a; . ../.env; set +a      # ERP_DEMO_PASSWORD
E2E_GATEWAY_URL=http://localhost:${PORT_GATEWAY}/api E2E_ERP_URL=http://localhost:${PORT_ERP}/api/v1 \
  uv run pytest e2e -v
```

- erp는 시험 시작 때 `POST /_eval/reset`으로 팩 고정 데이터 상태로 되돌립니다(`ERP_EVAL_RESET=1` 필요).
- 로컬 모델은 Ollama `qwen3.5:9b`(호스트 11434)를 씁니다. 모델 시험 하나에 수십 초~수 분 걸립니다.

## 결과

### 2026-11-20 19:50, develop `abdbfbb` 이후, M1 Pro 32GB(Docker 메모리 8GB)

| 시험 | 결과 |
|---|---|
| 승인함 승인 | 통과 |
| 대결 등록 뒤 대리 결재 | 통과 |
| 채팅 반차 신청·되돌리기 | 실패: agent → gateway LLM 출구가 422, 라우터는 fallback(`assistant`), 실행은 "모델을 부르지 못했습니다" (#89) |
| 규정 질의 근거 | 실패: 같은 422 (#89) |

시작 단계에서 찾은 것:

- rag가 빈 `RAG_EXTRA_DOCS`로 종료, web이 gateway보다 먼저 떠 nginx 종료(#90). 위 `compose.eval.yaml`로 우회했습니다.
- 위 `compose.eval.yaml`을 붙이면 rag가 개발 셋 표지·주입 문서를 읽은 채로 healthy가 됩니다.

#89가 고쳐지면 다시 돌려 이 표를 고칩니다.
