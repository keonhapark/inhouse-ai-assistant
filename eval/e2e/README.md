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
export LITELLM_MASTER_KEY=sk-<임의 값> ERP_EVAL_RESET=1 GATEWAY_EVAL_MODE=1 GATEWAY_EXTERNAL_LOG=/audit/external.jsonl \
  RAG_MARKERS_FILE=/eval/markers/dev.yaml RAG_EXTRA_DOCS=/eval/injections/dev.yaml
docker compose -f infra/compose.yaml --env-file .env --profile full up -d --build --wait

cd eval
set -a; . ../.env; set +a      # ERP_DEMO_PASSWORD
E2E_GATEWAY_URL=http://localhost:${PORT_GATEWAY}/api E2E_ERP_URL=http://localhost:${PORT_ERP}/api/v1 \
  uv run pytest e2e -v
```

- erp는 시험 시작 때 `POST /_eval/reset`으로 팩 고정 데이터 상태로 되돌립니다(`ERP_EVAL_RESET=1` 필요).
- rag는 시작할 때 문서 임베딩을 만들어 30초쯤 unhealthy일 수 있습니다. 그동안 `--wait`가 실패로 끝나면 `docker compose -p iaa-s5 ps`로 rag가 healthy가 된 뒤 시험을 돌립니다.
- 에이전트가 되묻으면 시험이 정해 둔 답(`followup`)으로 한두 번 답합니다. 휴가 신청은 인사 에이전트 정책상 되돌릴 수 있는 쓰기라 실행 승인 없이 실행될 수 있고, 승인 카드가 나오면 미리보기를 확인한 뒤 승인합니다.
- 로컬 모델은 Ollama `qwen3.5:9b`(호스트 11434)를 씁니다. 모델 시험 하나에 수십 초~수 분 걸립니다.

## 결과

### 2026-11-20 20:05, develop `8e5bdfd`, M1 Pro 32GB(Docker 메모리 8GB)

| 시험 | 결과 |
|---|---|
| 채팅 반차 신청·되돌리기 | 통과(인사 에이전트가 날짜·기간을 한 번 되물은 뒤 실행) |
| 규정 질의 근거 | 통과 |
| 승인함 승인 | 통과 |
| 대결 등록 뒤 대리 결재 | 통과 |

4개 통과, 146초. 같은 시험을 다시 돌리면 모델 답이 달라 시간과 되묻기 횟수가 달라질 수 있습니다.

### 2026-11-20 19:50, develop `abdbfbb` 이후(첫 실행)

- 2개 통과(승인함, 대결), 2개 실패: agent → gateway LLM 출구 422(#89, #96에서 고침)
- 시작 문제: rag가 빈 평가 변수로 종료, web이 gateway보다 먼저 시작(#90, #94·#97에서 고침)
- 첫 실행 뒤 하네스의 되묻기 판단을 고쳤습니다. 질문 목록 뒤에 서술문으로 끝나는 답을 놓쳐서, 답의 어느 줄이든 물음 모양으로 끝나면 되묻기로 봅니다(`harness/clarify.py`, 프로토콜 2절).
