# 도구 호출 측정 2026-11-21-toolcall-all-gguf

| 항목 | 값 |
|---|---|
| title | 도구 호출 측정 2026-11-21-toolcall-all-gguf |
| commit | 1c7c6f3cd6981d28fb1b25a08817fa362675d7cb |
| dirty | False |
| machine | Linux-5.15.167.4-microsoft-standard-WSL2-x86_64-with-glibc2.39 x86_64 |
| started_at | 2026-11-21T17:36:28+09:00 |
| items | /tmp/claude-1000/-home-keonha-orca-workspaces-inhouse-ai-assistant-eval/3f1a2a77-b0fc-4538-a785-330fb9a377b0/scratchpad/stack-dev/agent/eval_dev/tool_calls.jsonl |
| itemsSha256 | 20b53cd56de748ed0258de04eda5e9d317ea522d92ba95286c7ce4cdbc15b499 |
| itemCount | 60 |
| maxStage | None |
| model | local-gguf |
| variant | {'grammar': True, 'toolFilterK': 5, 'fewShot': True} |
| repeats | 1 |
| finished_at | 2026-11-21T18:13:50+09:00 |

- 기기: RTX 4070 SUPER 12GB, WSL2(Linux 5.15) Docker, Ollama 0.40.15(WSL 안, 모델 ext4, OLLAMA_CONTEXT_LENGTH 8192, MAX_LOADED_MODELS 3, KEEP_ALIVE 24h)
- 모델: local=qwen3.5:9b, local-gguf=qwen3.5:9b-q4_K_M, 이 PC에서는 둘 다 digest 56671c2ab938(같은 GGUF Q4_K_M, llama.cpp 실행기). 외부 기준 external=Claude Haiku 5.5
- 스택: develop 1c7c6f3, litellm·gateway(GATEWAY_EVAL_TOOLCALL=1)·agent(AGENT_EVAL_MODE=1)만, PACK_STAGE=2. 다른 세션은 Ollama를 쓰지 않음(리드가 차례를 줌). 동시 실행 1
- 변형: grammar + toolFilterK 5 + fewShot, 반복 3회 계획이었으나 1회(60개)에서 멈췄습니다. 이 기기에서 회차 중간값 23초, 60초 제한 초과(502)가 잦고 qwen 실행기 상주 메모리가 약 7GB로 WSL 메모리(12GB)를 다 써 OOM이 두 번 났기 때문입니다(그 두 부분 실행과 2회차 일부는 버림).

채점 규칙은 `contracts/eval/toolcall/README.md`입니다. 첫 행동만 보고, 실행 오류는 분모에서 뺍니다.

## 정확도

| 구분 | 맞음 |
|---|---|
| 전체(회차 단위) | 25/40 (62.5%, 45.8%~77.3%) |
| pass^1(항목 단위) | 25/40 (62.5%, 45.8%~77.3%) |
| 도구를 부른 것 중 인자 스키마 유효 | 24/24 (100.0%, 85.8%~100.0%) |
| 되묻기 모양으로 답함 | 7/40 (17.5%, 7.3%~32.8%) |

- 지어낸 필수 인자(정답에 없고 발화에 없는 값): 4개
- 지연(모델 호출): p50 8304ms, p95 45519ms
- 모델 위치: local 40회차

## 모델 위치별

| 구분 | 맞음 |
|---|---|
| local | 25/40 (62.5%, 45.8%~77.3%) |

## 유형별

| 구분 | 맞음 |
|---|---|
| clarify | 3/11 (27.3%, 6.0%~61.0%) |
| confusable | 0/1 (0.0%, 0.0%~97.5%) |
| direct | 17/21 (81.0%, 58.1%~94.6%) |
| resolve | 5/7 (71.4%, 29.0%~96.3%) |

## 단계별

| 구분 | 맞음 |
|---|---|
| 1 | 17/28 (60.7%, 40.6%~78.5%) |
| 2 | 8/12 (66.7%, 34.9%~90.1%) |

## 도구별(targetTool)

| 구분 | 맞음 |
|---|---|
| approval_get | 1/1 (100.0%, 2.5%~100.0%) |
| approval_list_mine | 0/1 (0.0%, 0.0%~97.5%) |
| approval_withdraw | 1/1 (100.0%, 2.5%~100.0%) |
| delegation_register | 1/2 (50.0%, 1.3%~98.7%) |
| delegation_revoke | 1/1 (100.0%, 2.5%~100.0%) |
| expense_request | 4/6 (66.7%, 22.3%~95.7%) |
| hr_get_my_profile | 1/1 (100.0%, 2.5%~100.0%) |
| leave_get_balance | 1/1 (100.0%, 2.5%~100.0%) |
| leave_request | 4/8 (50.0%, 15.7%~84.3%) |
| org_search_employees | 2/2 (100.0%, 15.8%~100.0%) |
| policy_search | 1/4 (25.0%, 0.6%~80.6%) |
| purchase_request | 4/6 (66.7%, 22.3%~95.7%) |
| room_cancel_reservation | 1/1 (100.0%, 2.5%~100.0%) |
| room_list_availability | 2/3 (66.7%, 9.4%~99.2%) |
| room_reserve | 1/2 (50.0%, 1.3%~98.7%) |

## 결과 분포(회차 단위)

| 결과 | 회차 |
|---|---|
| 정답 (맞음) | 24 |
| 실행 오류(분모 제외) | 20 |
| 부르지 않고 답함 | 9 |
| 부르지 않고 되물음 | 3 |
| 다른 도구 | 2 |
| 인자 틀림 | 1 |
| 확인 후 진행 (맞음) | 1 |

## 인자 틀림

| 항목 | 도구 | 틀린 인자 |
|---|---|---|
| tc-903 | leave_request | start_date, end_date |
