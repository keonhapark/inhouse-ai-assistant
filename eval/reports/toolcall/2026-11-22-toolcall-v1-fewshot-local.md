# 도구 호출 측정 toolcall-v1 fewShot local

| 항목 | 값 |
|---|---|
| title | 도구 호출 측정 toolcall-v1 fewShot local |
| commit | fe4aa1b8f46713f40f8c35ca6bcace17564eda03 |
| dirty | False |
| machine | Linux-5.15.167.4-microsoft-standard-WSL2-x86_64-with-glibc2.39 x86_64 |
| started_at | 2026-11-22T05:42:59+09:00 |
| items | items.jsonl |
| itemsSha256 | 815a14829991726b491594824c2f5f48e65fd97713dd252706aead39c814d36d |
| itemCount | 120 |
| maxStage | None |
| model | local |
| variant | {'fewShot': True} |
| repeats | 1 |
| bundle | toolcall-v1 `bf7066b5b7c5794836ec875ac1b4139b47b00a3693c5f60c3fafce2e0cdd123e` = 계약 표(파일 5개, 끝 줄바꿈 있음) |
| finished_at | 2026-11-22T05:53:16+09:00 |

- 기기: RTX 4070 SUPER 12GB, WSL2(Linux 5.15) Docker, Ollama 0.40.15(WSL 안, 모델 ext4, OLLAMA_CONTEXT_LENGTH 8192, MAX_LOADED_MODELS 3, KEEP_ALIVE 24h)
- 모델: local=qwen3.5:9b(digest 56671c2ab938, GGUF Q4_K_M), 외부 기준 external=Claude Haiku 5.5
- 스택: develop fe4aa1b, postgres·fake-erp·erp·litellm·gateway(GATEWAY_EVAL_TOOLCALL=1)·agent(AGENT_EVAL_MODE=1), PACK_STAGE=2, ERP_EVAL_RESET=1(setup 항목 전에 erp 초기화). 동시 실행 1, 이 시간 Ollama는 이 측정만 씀(리드가 차례를 줌)
- 변형에 thinking을 보내지 않았습니다(개발 묶음과 같이 모델·스택 기본값)
- 범위: 변형은 개발 묶음(agent/eval_dev, 60개) 결과를 보고 정했습니다. 문법 강제·전부 켬은 개발 묶음에서 gateway 60초 제한 초과 502가 많아(18/60, 20/60) 뺐습니다. 120개 전부(2단계 도구 포함)를 돌리고 단계별 표에 1단계 소계가 있습니다
- 변형: {"fewShot": true}, 반복 1
- 반복: 실행 시간(GPU 대기열) 때문에 fewShot·external은 1회만 돌렸습니다(사용자 결정, 결정 0007). 주 비교는 세 변형의 1회차끼리입니다. llama-server 프롬프트 캐시 상한: S0 local은 기본 8192MiB, fewShot·external은 OOM 뒤 Ollama를 LLAMA_ARG_CACHE_RAM=1024로 다시 띄운 뒤 돌렸습니다(출력에는 영향 없고 지연에만 영향 가능)
- fewShot local은 두 번 중단됐습니다. 05:40 OOM(28/120회차, 캐시 상한 8192MiB)과 05:41 리드 요청 멈춤(Ollama를 캐시 상한 1024MiB로 다시 띄우기 위해). 두 부분 실행은 열지 않고 버렸습니다(sha256 68660a5c082c54d1948f3650a32a4efad27d8f3841a2366df5d087ec6a06d333, 2b6777024d70ad01d9049ff7674b9dc25c6b5b19ec18177f4a1cb9ffe5a34aa8). 05:42에 처음부터 다시 돌린 결과입니다
- 생각 단계: 이 변형은 thinking을 보내지 않아 모델 기본값(qwen3.5:9b 생각 켬)으로 쟀습니다. 업무 실행 그래프는 #424 뒤 로컬 계획 호출이 생각 끔(AGENT_PLAN_REASONING_EFFORT 기본 none)이라, 이 값은 지금 에이전트가 실제로 도는 설정과 다릅니다. #491(#423)의 같은 입력 비교에서 생각 끔은 기대 도구 호출을 44/46에서 28/46으로 낮췄습니다(코랩 T4, 개발 묶음, 1회). 다시 잴지는 #423 결정 뒤 정합니다(#497)
- 회차 기록(.json·.rows.jsonl)은 문항 내용이 드러나는 result·mismatched·schema_errors를 빼고 error는 상태 코드만 남긴 공개 사본입니다(eval/tools/mask_toolcall.py). 보고서에서 인자 틀림 목록을 뺐습니다. 원본은 저장소 밖에 둡니다: 2026-11-22-toolcall-v1-fewshot-local.json sha256 1929e8e357c3442bc4de681ec428afd010d5f421f4a964e89cdadb7afccce939, 2026-11-22-toolcall-v1-fewshot-local.rows.jsonl sha256 25a4c44227b91e80e979bc517e3c998c900d0392b023fce14cc2b42ac79c80ff

채점 규칙은 `contracts/eval/toolcall/README.md`입니다. 첫 행동만 보고, 실행 오류는 분모에서 뺍니다.

## 정확도

| 구분 | 맞음 |
|---|---|
| 전체(회차 단위) | 93/118 (78.8%, 70.3%~85.8%) |
| pass^1(항목 단위) | 93/118 (78.8%, 70.3%~85.8%) |
| 도구를 부른 것 중 인자 스키마 유효 | 103/104 (99.0%, 94.8%~100.0%) |
| 되묻기 모양으로 답함 | 5/118 (4.2%, 1.4%~9.6%) |

- 지어낸 필수 인자(정답에 없고 발화에 없는 값): 1개
- 지연(모델 호출): p50 2942ms, p95 9873ms
- 모델 위치: local 118회차

## 모델 위치별

| 구분 | 맞음 |
|---|---|
| local | 93/118 (78.8%, 70.3%~85.8%) |

## 유형별

| 구분 | 맞음 |
|---|---|
| clarify | 10/17 (58.8%, 32.9%~81.6%) |
| confusable | 26/32 (81.2%, 63.6%~92.8%) |
| direct | 44/47 (93.6%, 82.5%~98.7%) |
| resolve | 13/22 (59.1%, 36.4%~79.3%) |

## 단계별

| 구분 | 맞음 |
|---|---|
| 1 | 83/104 (79.8%, 70.8%~87.0%) |
| 2 | 10/14 (71.4%, 41.9%~91.6%) |

## 도구별(targetTool)

| 구분 | 맞음 |
|---|---|
| approval_get | 6/7 (85.7%, 42.1%~99.6%) |
| approval_list_mine | 7/7 (100.0%, 59.0%~100.0%) |
| approval_withdraw | 6/7 (85.7%, 42.1%~99.6%) |
| delegation_list | 7/7 (100.0%, 59.0%~100.0%) |
| delegation_register | 2/7 (28.6%, 3.7%~71.0%) |
| delegation_revoke | 6/7 (85.7%, 42.1%~99.6%) |
| expense_request | 4/7 (57.1%, 18.4%~90.1%) |
| hr_get_my_profile | 7/7 (100.0%, 59.0%~100.0%) |
| leave_get_balance | 7/7 (100.0%, 59.0%~100.0%) |
| leave_request | 4/7 (57.1%, 18.4%~90.1%) |
| org_search_employees | 3/7 (42.9%, 9.9%~81.6%) |
| policy_search | 7/7 (100.0%, 59.0%~100.0%) |
| purchase_request | 6/7 (85.7%, 42.1%~99.6%) |
| room_cancel_reservation | 7/7 (100.0%, 59.0%~100.0%) |
| room_list_availability | 6/7 (85.7%, 42.1%~99.6%) |
| room_list_my_reservations | 7/7 (100.0%, 59.0%~100.0%) |
| room_reserve | 1/6 (16.7%, 0.4%~64.1%) |

## 결과 분포(회차 단위)

| 결과 | 회차 |
|---|---|
| 정답 (맞음) | 86 |
| 부르지 않고 답함 | 9 |
| 인자 틀림 | 8 |
| 다른 도구 | 8 |
| 대안 정답 (맞음) | 6 |
| 실행 오류(분모 제외) | 2 |
| 확인 후 진행 (맞음) | 1 |
