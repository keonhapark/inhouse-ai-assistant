# 도구 호출 측정 2026-11-21-toolcall-s1-grammar-gguf

| 항목 | 값 |
|---|---|
| title | 도구 호출 측정 2026-11-21-toolcall-s1-grammar-gguf |
| commit | 1c7c6f3cd6981d28fb1b25a08817fa362675d7cb |
| dirty | False |
| machine | Linux-5.15.167.4-microsoft-standard-WSL2-x86_64-with-glibc2.39 x86_64 |
| started_at | 2026-11-21T16:24:17+09:00 |
| items | /tmp/claude-1000/-home-keonha-orca-workspaces-inhouse-ai-assistant-eval/3f1a2a77-b0fc-4538-a785-330fb9a377b0/scratchpad/stack-dev/agent/eval_dev/tool_calls.jsonl |
| itemsSha256 | 20b53cd56de748ed0258de04eda5e9d317ea522d92ba95286c7ce4cdbc15b499 |
| itemCount | 60 |
| maxStage | None |
| model | local-gguf |
| variant | {'grammar': True} |
| repeats | 1 |
| finished_at | 2026-11-21T16:54:41+09:00 |

- 기기: RTX 4070 SUPER 12GB, WSL2(Linux 5.15) Docker, Ollama 0.40.15(WSL 안, 모델 ext4, OLLAMA_CONTEXT_LENGTH 8192, MAX_LOADED_MODELS 3, KEEP_ALIVE 24h)
- 모델: local=qwen3.5:9b, local-gguf=qwen3.5:9b-q4_K_M, 이 PC에서는 둘 다 digest 56671c2ab938(같은 GGUF Q4_K_M, llama.cpp 실행기). 외부 기준 external=Claude Haiku 5.5
- 스택: develop 1c7c6f3, litellm·gateway(GATEWAY_EVAL_TOOLCALL=1)·agent(AGENT_EVAL_MODE=1)만, PACK_STAGE=2. 다른 세션은 Ollama를 쓰지 않음(리드가 차례를 줌). 동시 실행 1
- 변형: {"grammar": true}, 반복 1

채점 규칙은 `contracts/eval/toolcall/README.md`입니다. 첫 행동만 보고, 실행 오류는 분모에서 뺍니다.

## 정확도

| 구분 | 맞음 |
|---|---|
| 전체(회차 단위) | 31/42 (73.8%, 58.0%~86.1%) |
| pass^1(항목 단위) | 31/42 (73.8%, 58.0%~86.1%) |
| 도구를 부른 것 중 인자 스키마 유효 | 28/28 (100.0%, 87.7%~100.0%) |
| 되묻기 모양으로 답함 | 7/42 (16.7%, 7.0%~31.4%) |

- 지어낸 필수 인자(정답에 없고 발화에 없는 값): 0개
- 지연(모델 호출): p50 9918ms, p95 49791ms
- 모델 위치: local 42회차

## 모델 위치별

| 구분 | 맞음 |
|---|---|
| local | 31/42 (73.8%, 58.0%~86.1%) |

## 유형별

| 구분 | 맞음 |
|---|---|
| clarify | 3/10 (30.0%, 6.7%~65.2%) |
| confusable | 2/2 (100.0%, 15.8%~100.0%) |
| direct | 22/23 (95.7%, 78.1%~99.9%) |
| resolve | 4/7 (57.1%, 18.4%~90.1%) |

## 단계별

| 구분 | 맞음 |
|---|---|
| 1 | 24/31 (77.4%, 58.9%~90.4%) |
| 2 | 7/11 (63.6%, 30.8%~89.1%) |

## 도구별(targetTool)

| 구분 | 맞음 |
|---|---|
| approval_get | 2/2 (100.0%, 15.8%~100.0%) |
| approval_list_mine | 2/3 (66.7%, 9.4%~99.2%) |
| approval_withdraw | 2/2 (100.0%, 15.8%~100.0%) |
| delegation_list | 1/1 (100.0%, 2.5%~100.0%) |
| delegation_revoke | 2/2 (100.0%, 15.8%~100.0%) |
| expense_request | 4/6 (66.7%, 22.3%~95.7%) |
| hr_get_my_profile | 1/1 (100.0%, 2.5%~100.0%) |
| leave_get_balance | 2/2 (100.0%, 15.8%~100.0%) |
| leave_request | 3/7 (42.9%, 9.9%~81.6%) |
| org_search_employees | 1/1 (100.0%, 2.5%~100.0%) |
| policy_search | 4/4 (100.0%, 39.8%~100.0%) |
| purchase_request | 3/5 (60.0%, 14.7%~94.7%) |
| room_cancel_reservation | 1/1 (100.0%, 2.5%~100.0%) |
| room_list_availability | 2/4 (50.0%, 6.8%~93.2%) |
| room_reserve | 1/1 (100.0%, 2.5%~100.0%) |

## 결과 분포(회차 단위)

| 결과 | 회차 |
|---|---|
| 정답 (맞음) | 30 |
| 실행 오류(분모 제외) | 18 |
| 부르지 않고 답함 | 7 |
| 부르지 않고 되물음 | 3 |
| 인자 틀림 | 1 |
| 확인 후 진행 (맞음) | 1 |

## 인자 틀림

| 항목 | 도구 | 틀린 인자 |
|---|---|---|
| tc-905 | leave_request | leave_type |
