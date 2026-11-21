# 도구 호출 측정 2026-11-21-toolcall-s0-local

| 항목 | 값 |
|---|---|
| title | 도구 호출 측정 2026-11-21-toolcall-s0-local |
| commit | 1c7c6f3cd6981d28fb1b25a08817fa362675d7cb |
| dirty | False |
| machine | Linux-5.15.167.4-microsoft-standard-WSL2-x86_64-with-glibc2.39 x86_64 |
| started_at | 2026-11-21T15:37:16+09:00 |
| items | /tmp/claude-1000/-home-keonha-orca-workspaces-inhouse-ai-assistant-eval/3f1a2a77-b0fc-4538-a785-330fb9a377b0/scratchpad/stack-dev/agent/eval_dev/tool_calls.jsonl |
| itemsSha256 | 20b53cd56de748ed0258de04eda5e9d317ea522d92ba95286c7ce4cdbc15b499 |
| itemCount | 60 |
| maxStage | None |
| model | local |
| variant | {} |
| repeats | 3 |
| finished_at | 2026-11-21T15:50:00+09:00 |

- 기기: RTX 4070 SUPER 12GB, WSL2(Linux 5.15) Docker, Ollama 0.40.15(WSL 안, 모델 ext4, OLLAMA_CONTEXT_LENGTH 8192, MAX_LOADED_MODELS 3, KEEP_ALIVE 24h)
- 모델: local=qwen3.5:9b, local-gguf=qwen3.5:9b-q4_K_M, 이 PC에서는 둘 다 digest 56671c2ab938(같은 GGUF Q4_K_M, llama.cpp 실행기). 외부 기준 external=Claude Haiku 5.5
- 스택: develop 1c7c6f3, litellm·gateway(GATEWAY_EVAL_TOOLCALL=1)·agent(AGENT_EVAL_MODE=1)만, PACK_STAGE=2. 다른 세션은 Ollama를 쓰지 않음(리드가 차례를 줌). 동시 실행 1
- 변형: {}, 반복 3

채점 규칙은 `contracts/eval/toolcall/README.md`입니다. 첫 행동만 보고, 실행 오류는 분모에서 뺍니다.

## 정확도

| 구분 | 맞음 |
|---|---|
| 전체(회차 단위) | 135/180 (75.0%, 68.0%~81.1%) |
| pass^3(항목 단위) | 43/60 (71.7%, 58.6%~82.5%) |
| 도구를 부른 것 중 인자 스키마 유효 | 141/144 (97.9%, 94.0%~99.6%) |
| 되묻기 모양으로 답함 | 18/180 (10.0%, 6.0%~15.3%) |

- 지어낸 필수 인자(정답에 없고 발화에 없는 값): 0개
- 지연(모델 호출): p50 4198ms, p95 8845ms
- 모델 위치: local 180회차

## 모델 위치별

| 구분 | 맞음 |
|---|---|
| local | 135/180 (75.0%, 68.0%~81.1%) |

## 유형별

| 구분 | 맞음 |
|---|---|
| clarify | 12/33 (36.4%, 20.4%~54.9%) |
| confusable | 9/12 (75.0%, 42.8%~94.5%) |
| direct | 96/108 (88.9%, 81.4%~94.1%) |
| resolve | 18/27 (66.7%, 46.0%~83.5%) |

## 단계별

| 구분 | 맞음 |
|---|---|
| 1 | 117/144 (81.2%, 73.9%~87.3%) |
| 2 | 18/36 (50.0%, 32.9%~67.1%) |

## 도구별(targetTool)

| 구분 | 맞음 |
|---|---|
| approval_get | 6/6 (100.0%, 54.1%~100.0%) |
| approval_list_mine | 12/12 (100.0%, 73.5%~100.0%) |
| approval_withdraw | 6/6 (100.0%, 54.1%~100.0%) |
| delegation_list | 5/6 (83.3%, 35.9%~99.6%) |
| delegation_register | 3/9 (33.3%, 7.5%~70.1%) |
| delegation_revoke | 6/6 (100.0%, 54.1%~100.0%) |
| expense_request | 6/18 (33.3%, 13.3%~59.0%) |
| hr_get_my_profile | 3/3 (100.0%, 29.2%~100.0%) |
| leave_get_balance | 6/6 (100.0%, 54.1%~100.0%) |
| leave_request | 22/30 (73.3%, 54.1%~87.7%) |
| org_search_employees | 6/6 (100.0%, 54.1%~100.0%) |
| policy_search | 12/12 (100.0%, 73.5%~100.0%) |
| purchase_request | 12/18 (66.7%, 41.0%~86.7%) |
| room_cancel_reservation | 6/6 (100.0%, 54.1%~100.0%) |
| room_list_availability | 9/18 (50.0%, 26.0%~74.0%) |
| room_list_my_reservations | 6/6 (100.0%, 54.1%~100.0%) |
| room_reserve | 9/12 (75.0%, 42.8%~94.5%) |

## 결과 분포(회차 단위)

| 결과 | 회차 |
|---|---|
| 정답 (맞음) | 132 |
| 부르지 않고 답함 | 18 |
| 인자 틀림 | 13 |
| 되물어야 하는데 부름 | 6 |
| 다른 도구 | 5 |
| 부르지 않고 되물음 | 3 |
| 확인 후 진행 (맞음) | 3 |

## 인자 틀림

| 항목 | 도구 | 틀린 인자 |
|---|---|---|
| tc-920 | delegation_list | role |
| tc-923 | delegation_register | formTypes |
| tc-944 | expense_request | spent_on |
| tc-945 | expense_request | spent_on |
| tc-946 | expense_request | spent_on |
| tc-923 | delegation_register | formTypes |
| tc-944 | expense_request | spent_on |
| tc-945 | expense_request | spent_on |
| tc-946 | expense_request | spent_on |
| tc-923 | delegation_register | formTypes |
| tc-944 | expense_request | spent_on |
| tc-945 | expense_request | spent_on |
| tc-946 | expense_request | spent_on |
