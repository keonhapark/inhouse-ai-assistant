# 도구 호출 측정 toolcall-v1 S0 local

| 항목 | 값 |
|---|---|
| title | 도구 호출 측정 toolcall-v1 S0 local |
| commit | fe4aa1b8f46713f40f8c35ca6bcace17564eda03 |
| dirty | False |
| machine | Linux-5.15.167.4-microsoft-standard-WSL2-x86_64-with-glibc2.39 x86_64 |
| started_at | 2026-11-22T05:08:07+09:00 |
| items | items.jsonl |
| itemsSha256 | 815a14829991726b491594824c2f5f48e65fd97713dd252706aead39c814d36d |
| itemCount | 120 |
| maxStage | None |
| model | local |
| variant | {} |
| repeats | 3 |
| bundle | toolcall-v1 `bf7066b5b7c5794836ec875ac1b4139b47b00a3693c5f60c3fafce2e0cdd123e` = 계약 표(파일 5개, 끝 줄바꿈 있음) |
| finished_at | 2026-11-22T05:36:39+09:00 |

- 기기: RTX 4070 SUPER 12GB, WSL2(Linux 5.15) Docker, Ollama 0.40.15(WSL 안, 모델 ext4, OLLAMA_CONTEXT_LENGTH 8192, MAX_LOADED_MODELS 3, KEEP_ALIVE 24h)
- 모델: local=qwen3.5:9b(digest 56671c2ab938, GGUF Q4_K_M), 외부 기준 external=Claude Haiku 5.5
- 스택: develop fe4aa1b, postgres·fake-erp·erp·litellm·gateway(GATEWAY_EVAL_TOOLCALL=1)·agent(AGENT_EVAL_MODE=1), PACK_STAGE=2, ERP_EVAL_RESET=1(setup 항목 전에 erp 초기화). 동시 실행 1, 이 시간 Ollama는 이 측정만 씀(리드가 차례를 줌)
- 변형에 thinking을 보내지 않았습니다(개발 묶음과 같이 모델·스택 기본값)
- 범위: 변형은 개발 묶음(agent/eval_dev, 60개) 결과를 보고 정했습니다. 문법 강제·전부 켬은 개발 묶음에서 gateway 60초 제한 초과 502가 많아(18/60, 20/60) 뺐습니다. 120개 전부(2단계 도구 포함)를 돌리고 단계별 표에 1단계 소계가 있습니다
- 변형: {}, 반복 3
- 05:07 WSL 메모리 부족(OOM, 측정 밖 작업이 메모리를 같이 씀)으로 qwen 실행기가 죽어 S0 local이 72/360회차에서 멈췄습니다. 다시 시작한 이유는 OOM이고 결과 때문이 아닙니다. 부분 실행은 버리고 05:08에 처음부터 다시 돌렸습니다(버린 .rows.jsonl sha256 4bcd3589d3e9fa5a94a3a87dde866b657492330f9f4e0fb32a1008f5dea2da02). 중단 전 05:01에 진행 확인으로 첫 28회차의 결과 분포와 오류 2건의 상태 코드를 본 적이 있고, 중단 뒤에는 버린 결과를 집계하거나 보지 않았습니다
- llama-server 프롬프트 캐시 상한은 기본 8192MiB였습니다(fewShot·external은 1024MiB, 출력에는 영향 없고 지연에만 영향 가능)
- 주 비교는 1회차(pass^1)끼리입니다(eval/reports/toolcall/2026-11-22-toolcall-v1-compare.md). 이 보고서의 pass^3은 부록입니다
- 회차 기록(.json·.rows.jsonl)은 문항 내용이 드러나는 result·mismatched·schema_errors를 빼고 error는 상태 코드만 남긴 공개 사본입니다(eval/tools/mask_toolcall.py). 보고서에서 인자 틀림 목록을 뺐습니다. 원본은 저장소 밖에 둡니다: 2026-11-22-toolcall-v1-s0-local.json sha256 b811bb7217e68e9c7bd6bed554aebd9b9c4612b9db875c0a18dcece6a7d195ba, 2026-11-22-toolcall-v1-s0-local.rows.jsonl sha256 c8a94025819f267bdb3ff6579a94ef7c26de7bf59e28a5356fd1cc50af99862b

채점 규칙은 `contracts/eval/toolcall/README.md`입니다. 첫 행동만 보고, 실행 오류는 분모에서 뺍니다.

## 정확도

| 구분 | 맞음 |
|---|---|
| 전체(회차 단위) | 276/355 (77.7%, 73.1%~82.0%) |
| pass^3(항목 단위) | 89/120 (74.2%, 65.4%~81.7%) |
| 도구를 부른 것 중 인자 스키마 유효 | 312/318 (98.1%, 95.9%~99.3%) |
| 되묻기 모양으로 답함 | 21/355 (5.9%, 3.7%~8.9%) |

- 지어낸 필수 인자(정답에 없고 발화에 없는 값): 3개
- 지연(모델 호출): p50 2764ms, p95 9243ms
- 모델 위치: local 355회차

## 모델 위치별

| 구분 | 맞음 |
|---|---|
| local | 276/355 (77.7%, 73.1%~82.0%) |

## 유형별

| 구분 | 맞음 |
|---|---|
| clarify | 36/51 (70.6%, 56.2%~82.5%) |
| confusable | 79/94 (84.0%, 75.0%~90.8%) |
| direct | 126/141 (89.4%, 83.1%~93.9%) |
| resolve | 35/69 (50.7%, 38.4%~63.0%) |

## 단계별

| 구분 | 맞음 |
|---|---|
| 1 | 255/313 (81.5%, 76.7%~85.6%) |
| 2 | 21/42 (50.0%, 34.2%~65.8%) |

## 도구별(targetTool)

| 구분 | 맞음 |
|---|---|
| approval_get | 17/21 (81.0%, 58.1%~94.6%) |
| approval_list_mine | 21/21 (100.0%, 83.9%~100.0%) |
| approval_withdraw | 17/19 (89.5%, 66.9%~98.7%) |
| delegation_list | 21/21 (100.0%, 83.9%~100.0%) |
| delegation_register | 4/21 (19.0%, 5.4%~41.9%) |
| delegation_revoke | 18/21 (85.7%, 63.7%~97.0%) |
| expense_request | 3/21 (14.3%, 3.0%~36.3%) |
| hr_get_my_profile | 21/21 (100.0%, 83.9%~100.0%) |
| leave_get_balance | 21/21 (100.0%, 83.9%~100.0%) |
| leave_request | 16/22 (72.7%, 49.8%~89.3%) |
| org_search_employees | 9/21 (42.9%, 21.8%~66.0%) |
| policy_search | 21/21 (100.0%, 83.9%~100.0%) |
| purchase_request | 18/21 (85.7%, 63.7%~97.0%) |
| room_cancel_reservation | 21/21 (100.0%, 83.9%~100.0%) |
| room_list_availability | 20/20 (100.0%, 83.2%~100.0%) |
| room_list_my_reservations | 19/21 (90.5%, 69.6%~98.8%) |
| room_reserve | 9/21 (42.9%, 21.8%~66.0%) |

## 결과 분포(회차 단위)

| 결과 | 회차 |
|---|---|
| 정답 (맞음) | 253 |
| 인자 틀림 | 32 |
| 다른 도구 | 29 |
| 대안 정답 (맞음) | 21 |
| 부르지 않고 답함 | 16 |
| 실행 오류(분모 제외) | 5 |
| 확인 후 진행 (맞음) | 2 |
| 부르지 않고 되물음 | 1 |
| 되물어야 하는데 부름 | 1 |
