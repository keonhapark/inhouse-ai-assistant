# 도구 호출 측정 toolcall-v1 외부 기준

| 항목 | 값 |
|---|---|
| title | 도구 호출 측정 toolcall-v1 외부 기준 |
| commit | fe4aa1b8f46713f40f8c35ca6bcace17564eda03 |
| dirty | False |
| machine | Linux-5.15.167.4-microsoft-standard-WSL2-x86_64-with-glibc2.39 x86_64 |
| started_at | 2026-11-22T05:53:17+09:00 |
| items | items.jsonl |
| itemsSha256 | 815a14829991726b491594824c2f5f48e65fd97713dd252706aead39c814d36d |
| itemCount | 120 |
| maxStage | None |
| model | external |
| variant | {} |
| repeats | 1 |
| bundle | toolcall-v1 `bf7066b5b7c5794836ec875ac1b4139b47b00a3693c5f60c3fafce2e0cdd123e` = 계약 표(파일 5개, 끝 줄바꿈 있음) |
| finished_at | 2026-11-22T05:55:55+09:00 |

- 기기: RTX 4070 SUPER 12GB, WSL2(Linux 5.15) Docker, Ollama 0.40.15(WSL 안, 모델 ext4, OLLAMA_CONTEXT_LENGTH 8192, MAX_LOADED_MODELS 3, KEEP_ALIVE 24h)
- 모델: local=qwen3.5:9b(digest 56671c2ab938, GGUF Q4_K_M), 외부 기준 external=Claude Haiku 5.5
- 스택: develop fe4aa1b, postgres·fake-erp·erp·litellm·gateway(GATEWAY_EVAL_TOOLCALL=1)·agent(AGENT_EVAL_MODE=1), PACK_STAGE=2, ERP_EVAL_RESET=1(setup 항목 전에 erp 초기화). 동시 실행 1, 이 시간 Ollama는 이 측정만 씀(리드가 차례를 줌)
- 변형에 thinking을 보내지 않았습니다(개발 묶음과 같이 모델·스택 기본값)
- 범위: 변형은 개발 묶음(agent/eval_dev, 60개) 결과를 보고 정했습니다. 문법 강제·전부 켬은 개발 묶음에서 gateway 60초 제한 초과 502가 많아(18/60, 20/60) 뺐습니다. 120개 전부(2단계 도구 포함)를 돌리고 단계별 표에 1단계 소계가 있습니다
- 변형: {}, 반복 1
- 반복: 실행 시간(GPU 대기열) 때문에 fewShot·external은 1회만 돌렸습니다(사용자 결정, 결정 0007). 주 비교는 세 변형의 1회차끼리입니다. llama-server 프롬프트 캐시 상한: S0 local은 기본 8192MiB, fewShot·external은 OOM 뒤 Ollama를 LLAMA_ARG_CACHE_RAM=1024로 다시 띄운 뒤 돌렸습니다(출력에는 영향 없고 지연에만 영향 가능)
- 생각 단계: external 실행의 hr 44회차는 업무 주제 로컬 강제로 gateway가 로컬로 돌린 호출이고 #434로 생각 끔(reasoning_effort none)이었습니다. 이 묶음의 낮은 점수(25/44, 같은 항목 S0 local 33/43)는 #491의 생각 끔·켬 차이와 방향이 같습니다. 외부로 간 76회차는 Haiku입니다(#497)
- 회차 기록(.json·.rows.jsonl)은 문항 내용이 드러나는 result·mismatched·schema_errors를 빼고 error는 상태 코드만 남긴 공개 사본입니다(eval/tools/mask_toolcall.py). 보고서에서 인자 틀림 목록을 뺐습니다. 원본은 저장소 밖에 둡니다: 2026-11-22-toolcall-v1-external.json sha256 f34bb05ba548de2a305d5a13c2b5fc6f5e767b8a687ef6ab9da495c45e3b391f, 2026-11-22-toolcall-v1-external.rows.jsonl sha256 ca47604076799311030da5c8d07740b9632bb2a0ff421005962dc3b157c0e5ba

채점 규칙은 `contracts/eval/toolcall/README.md`입니다. 첫 행동만 보고, 실행 오류는 분모에서 뺍니다.

## 정확도

| 구분 | 맞음 |
|---|---|
| 전체(회차 단위) | 88/120 (73.3%, 64.5%~81.0%) |
| pass^1(항목 단위) | 88/120 (73.3%, 64.5%~81.0%) |
| 도구를 부른 것 중 인자 스키마 유효 | 93/93 (100.0%, 96.1%~100.0%) |
| 되묻기 모양으로 답함 | 11/120 (9.2%, 4.7%~15.8%) |

- 지어낸 필수 인자(정답에 없고 발화에 없는 값): 0개
- 지연(모델 호출): p50 1162ms, p95 1799ms
- 모델 위치: external 76회차, local 44회차

## 모델 위치별

| 구분 | 맞음 |
|---|---|
| external | 63/76 (82.9%, 72.5%~90.6%) |
| local | 25/44 (56.8%, 41.0%~71.7%) |

## 유형별

| 구분 | 맞음 |
|---|---|
| clarify | 10/18 (55.6%, 30.8%~78.5%) |
| confusable | 26/32 (81.2%, 63.6%~92.8%) |
| direct | 41/47 (87.2%, 74.3%~95.2%) |
| resolve | 11/23 (47.8%, 26.8%~69.4%) |

## 단계별

| 구분 | 맞음 |
|---|---|
| 1 | 77/106 (72.6%, 63.1%~80.9%) |
| 2 | 11/14 (78.6%, 49.2%~95.3%) |

## 도구별(targetTool)

| 구분 | 맞음 |
|---|---|
| approval_get | 7/7 (100.0%, 59.0%~100.0%) |
| approval_list_mine | 7/7 (100.0%, 59.0%~100.0%) |
| approval_withdraw | 4/7 (57.1%, 18.4%~90.1%) |
| delegation_list | 5/7 (71.4%, 29.0%~96.3%) |
| delegation_register | 1/7 (14.3%, 0.4%~57.9%) |
| delegation_revoke | 4/7 (57.1%, 18.4%~90.1%) |
| expense_request | 5/7 (71.4%, 29.0%~96.3%) |
| hr_get_my_profile | 7/7 (100.0%, 59.0%~100.0%) |
| leave_get_balance | 7/7 (100.0%, 59.0%~100.0%) |
| leave_request | 3/8 (37.5%, 8.5%~75.5%) |
| org_search_employees | 3/7 (42.9%, 9.9%~81.6%) |
| policy_search | 7/7 (100.0%, 59.0%~100.0%) |
| purchase_request | 6/7 (85.7%, 42.1%~99.6%) |
| room_cancel_reservation | 7/7 (100.0%, 59.0%~100.0%) |
| room_list_availability | 6/7 (85.7%, 42.1%~99.6%) |
| room_list_my_reservations | 7/7 (100.0%, 59.0%~100.0%) |
| room_reserve | 2/7 (28.6%, 3.7%~71.0%) |

## 결과 분포(회차 단위)

| 결과 | 회차 |
|---|---|
| 정답 (맞음) | 81 |
| 부르지 않고 답함 | 16 |
| 다른 도구 | 9 |
| 대안 정답 (맞음) | 5 |
| 인자 틀림 | 4 |
| 부르지 않고 되물음 | 3 |
| 확인 후 진행 (맞음) | 2 |
