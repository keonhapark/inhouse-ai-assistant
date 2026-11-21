# 도구 호출 측정 2026-11-21-toolcall-s3-fewshot-local

| 항목 | 값 |
|---|---|
| title | 도구 호출 측정 2026-11-21-toolcall-s3-fewshot-local |
| commit | 1c7c6f3cd6981d28fb1b25a08817fa362675d7cb |
| dirty | False |
| machine | Linux-5.15.167.4-microsoft-standard-WSL2-x86_64-with-glibc2.39 x86_64 |
| started_at | 2026-11-21T15:56:41+09:00 |
| items | /tmp/claude-1000/-home-keonha-orca-workspaces-inhouse-ai-assistant-eval/3f1a2a77-b0fc-4538-a785-330fb9a377b0/scratchpad/stack-dev/agent/eval_dev/tool_calls.jsonl |
| itemsSha256 | 20b53cd56de748ed0258de04eda5e9d317ea522d92ba95286c7ce4cdbc15b499 |
| itemCount | 60 |
| maxStage | None |
| model | local |
| variant | {'fewShot': True} |
| repeats | 1 |
| finished_at | 2026-11-21T16:02:49+09:00 |

- 기기: RTX 4070 SUPER 12GB, WSL2(Linux 5.15) Docker, Ollama 0.40.15(WSL 안, 모델 ext4, OLLAMA_CONTEXT_LENGTH 8192, MAX_LOADED_MODELS 3, KEEP_ALIVE 24h)
- 모델: local=qwen3.5:9b, local-gguf=qwen3.5:9b-q4_K_M, 이 PC에서는 둘 다 digest 56671c2ab938(같은 GGUF Q4_K_M, llama.cpp 실행기). 외부 기준 external=Claude Haiku 5.5
- 스택: develop 1c7c6f3, litellm·gateway(GATEWAY_EVAL_TOOLCALL=1)·agent(AGENT_EVAL_MODE=1)만, PACK_STAGE=2. 다른 세션은 Ollama를 쓰지 않음(리드가 차례를 줌). 동시 실행 1
- 변형: {"fewShot": true}, 반복 1

채점 규칙은 `contracts/eval/toolcall/README.md`입니다. 첫 행동만 보고, 실행 오류는 분모에서 뺍니다.

## 정확도

| 구분 | 맞음 |
|---|---|
| 전체(회차 단위) | 50/58 (86.2%, 74.6%~93.9%) |
| pass^1(항목 단위) | 50/58 (86.2%, 74.6%~93.9%) |
| 도구를 부른 것 중 인자 스키마 유효 | 47/47 (100.0%, 92.5%~100.0%) |
| 되묻기 모양으로 답함 | 5/58 (8.6%, 2.9%~19.0%) |

- 지어낸 필수 인자(정답에 없고 발화에 없는 값): 1개
- 지연(모델 호출): p50 3904ms, p95 8258ms
- 모델 위치: local 58회차

## 모델 위치별

| 구분 | 맞음 |
|---|---|
| local | 50/58 (86.2%, 74.6%~93.9%) |

## 유형별

| 구분 | 맞음 |
|---|---|
| clarify | 4/10 (40.0%, 12.2%~73.8%) |
| confusable | 2/4 (50.0%, 6.8%~93.2%) |
| direct | 35/35 (100.0%, 90.0%~100.0%) |
| resolve | 9/9 (100.0%, 66.4%~100.0%) |

## 단계별

| 구분 | 맞음 |
|---|---|
| 1 | 41/46 (89.1%, 76.4%~96.4%) |
| 2 | 9/12 (75.0%, 42.8%~94.5%) |

## 도구별(targetTool)

| 구분 | 맞음 |
|---|---|
| approval_get | 2/2 (100.0%, 15.8%~100.0%) |
| approval_list_mine | 4/4 (100.0%, 39.8%~100.0%) |
| approval_withdraw | 2/2 (100.0%, 15.8%~100.0%) |
| delegation_list | 2/2 (100.0%, 15.8%~100.0%) |
| delegation_register | 1/1 (100.0%, 2.5%~100.0%) |
| delegation_revoke | 2/2 (100.0%, 15.8%~100.0%) |
| expense_request | 5/6 (83.3%, 35.9%~99.6%) |
| hr_get_my_profile | 1/1 (100.0%, 2.5%~100.0%) |
| leave_get_balance | 2/2 (100.0%, 15.8%~100.0%) |
| leave_request | 9/10 (90.0%, 55.5%~99.7%) |
| org_search_employees | 2/2 (100.0%, 15.8%~100.0%) |
| policy_search | 4/4 (100.0%, 39.8%~100.0%) |
| purchase_request | 4/6 (66.7%, 22.3%~95.7%) |
| room_cancel_reservation | 1/2 (50.0%, 1.3%~98.7%) |
| room_list_availability | 4/6 (66.7%, 22.3%~95.7%) |
| room_list_my_reservations | 2/2 (100.0%, 15.8%~100.0%) |
| room_reserve | 3/4 (75.0%, 19.4%~99.4%) |

## 결과 분포(회차 단위)

| 결과 | 회차 |
|---|---|
| 정답 (맞음) | 49 |
| 부르지 않고 답함 | 6 |
| 실행 오류(분모 제외) | 2 |
| 확인 후 진행 (맞음) | 1 |
| 다른 도구 | 1 |
| 인자 틀림 | 1 |

## 인자 틀림

| 항목 | 도구 | 틀린 인자 |
|---|---|---|
| tc-941 | room_list_my_reservations | date |
