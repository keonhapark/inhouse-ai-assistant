# 도구 호출 측정 2026-11-21-toolcall-s0-external

| 항목 | 값 |
|---|---|
| title | 도구 호출 측정 2026-11-21-toolcall-s0-external |
| commit | 1c7c6f3cd6981d28fb1b25a08817fa362675d7cb |
| dirty | False |
| machine | Linux-5.15.167.4-microsoft-standard-WSL2-x86_64-with-glibc2.39 x86_64 |
| started_at | 2026-11-21T16:58:56+09:00 |
| items | agent/eval_dev/tool_calls.jsonl |
| itemsSha256 | 20b53cd56de748ed0258de04eda5e9d317ea522d92ba95286c7ce4cdbc15b499 |
| itemCount | 60 |
| maxStage | None |
| model | external |
| variant | {} |
| repeats | 3 |
| finished_at | 2026-11-21T17:07:09+09:00 |

- 기기: RTX 4070 SUPER 12GB, WSL2(Linux 5.15) Docker, Ollama 0.40.15(WSL 안, 모델 ext4, OLLAMA_CONTEXT_LENGTH 8192, MAX_LOADED_MODELS 3, KEEP_ALIVE 24h)
- 모델: local=qwen3.5:9b, local-gguf=qwen3.5:9b-q4_K_M, 이 PC에서는 둘 다 digest 56671c2ab938(같은 GGUF Q4_K_M, llama.cpp 실행기). 외부 기준 external=Claude Haiku 5.5
- 스택: develop 1c7c6f3, litellm·gateway(GATEWAY_EVAL_TOOLCALL=1)·agent(AGENT_EVAL_MODE=1)만, PACK_STAGE=2. 다른 세션은 Ollama를 쓰지 않음(리드가 차례를 줌). 동시 실행 1
- 변형: {}, 반복 3, 외부 기준(Ollama 안 씀)

채점 규칙은 `contracts/eval/toolcall/README.md`입니다. 첫 행동만 보고, 실행 오류는 분모에서 뺍니다.

## 정확도

| 구분 | 맞음 |
|---|---|
| 전체(회차 단위) | 150/180 (83.3%, 77.1%~88.5%) |
| pass^3(항목 단위) | 48/60 (80.0%, 67.7%~89.2%) |
| 도구를 부른 것 중 인자 스키마 유효 | 143/143 (100.0%, 97.5%~100.0%) |
| 되묻기 모양으로 답함 | 9/180 (5.0%, 2.3%~9.3%) |

- 지어낸 필수 인자(정답에 없고 발화에 없는 값): 0개
- 지연(모델 호출): p50 1510ms, p95 5289ms
- 모델 위치: external 117회차, local 63회차

## 모델 위치별

| 구분 | 맞음 |
|---|---|
| external | 98/117 (83.8%, 75.8%~89.9%) |
| local | 52/63 (82.5%, 70.9%~90.9%) |

## 유형별

| 구분 | 맞음 |
|---|---|
| clarify | 8/33 (24.2%, 11.1%~42.3%) |
| confusable | 12/12 (100.0%, 73.5%~100.0%) |
| direct | 104/108 (96.3%, 90.8%~99.0%) |
| resolve | 26/27 (96.3%, 81.0%~99.9%) |

## 단계별

| 구분 | 맞음 |
|---|---|
| 1 | 124/144 (86.1%, 79.4%~91.3%) |
| 2 | 26/36 (72.2%, 54.8%~85.8%) |

## 도구별(targetTool)

| 구분 | 맞음 |
|---|---|
| approval_get | 6/6 (100.0%, 54.1%~100.0%) |
| approval_list_mine | 12/12 (100.0%, 73.5%~100.0%) |
| approval_withdraw | 6/6 (100.0%, 54.1%~100.0%) |
| delegation_list | 5/6 (83.3%, 35.9%~99.6%) |
| delegation_register | 3/9 (33.3%, 7.5%~70.1%) |
| delegation_revoke | 6/6 (100.0%, 54.1%~100.0%) |
| expense_request | 12/18 (66.7%, 41.0%~86.7%) |
| hr_get_my_profile | 3/3 (100.0%, 29.2%~100.0%) |
| leave_get_balance | 6/6 (100.0%, 54.1%~100.0%) |
| leave_request | 26/30 (86.7%, 69.3%~96.2%) |
| org_search_employees | 6/6 (100.0%, 54.1%~100.0%) |
| policy_search | 12/12 (100.0%, 73.5%~100.0%) |
| purchase_request | 14/18 (77.8%, 52.4%~93.6%) |
| room_cancel_reservation | 6/6 (100.0%, 54.1%~100.0%) |
| room_list_availability | 9/18 (50.0%, 26.0%~74.0%) |
| room_list_my_reservations | 6/6 (100.0%, 54.1%~100.0%) |
| room_reserve | 12/12 (100.0%, 73.5%~100.0%) |

## 결과 분포(회차 단위)

| 결과 | 회차 |
|---|---|
| 정답 (맞음) | 150 |
| 부르지 않고 답함 | 28 |
| 부르지 않고 되물음 | 1 |
| 인자 틀림 | 1 |

## 인자 틀림

| 항목 | 도구 | 틀린 인자 |
|---|---|---|
| tc-920 | delegation_list | role |
