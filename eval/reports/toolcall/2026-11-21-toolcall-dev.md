# 도구 호출 측정: 개발 묶음 변형 비교(2026-11-21)

#103·#237. 로컬 모델이 업무 실행의 첫 계획 호출에서 도구를 맞게 고르고 인자를 맞게 채우는지, 장치(ToolCallVariant)를 하나씩 켜고 외부 모델과 견줍니다. 채점 규칙은 `contracts/eval/toolcall/README.md`, 채점기는 `eval/harness/toolcall.py`입니다.

**개발 묶음 결과입니다.** 항목(`agent/eval_dev/tool_calls.jsonl`, 60개, 기준일 2027-03-10)은 few-shot 예시와 프롬프트를 다듬는 데 쓰는 셋이라, 예시를 켠 변형(fewShot, 전부 켬)은 같은 묶음에서 뽑은 예시로 같은 묶음을 잰 값입니다. 주 결과는 확인 묶음(toolcall-v1, 120개)으로 한 번만 냅니다.

## 실행 조건

- 기기: RTX 4070 SUPER 12GB, WSL2(Linux 5.15) Docker. Ollama 0.40.15(WSL 안, 모델 ext4, 문맥 8192, 동시 3모델, 24시간 유지)
- 모델: `local`=qwen3.5:9b, `local-gguf`=qwen3.5:9b-q4_K_M. 이 PC에서는 둘 다 digest 56671c2ab938(같은 GGUF Q4_K_M, llama.cpp 실행기)이라 모델은 같고 별칭만 다릅니다. `local`은 구조화 출력을 지원하지 않는다고 설정돼 있어(litellm `supports_response_format: false`) 문법 강제가 든 변형은 `local-gguf`로 돌렸습니다. 외부 기준 `external`=Claude Haiku 5.5
- 스택: develop 1c7c6f3, litellm·gateway(`GATEWAY_EVAL_TOOLCALL=1`)·agent(`AGENT_EVAL_MODE=1`)만, `PACK_STAGE=2`. 동시 실행 1. 실행 중 Ollama는 이 측정만 썼습니다
- 장치 기준: #103에 S0~S3 정의가 없어 agent 계약 `ToolCallVariant`의 장치로 나눴습니다(S0=장치 없음, 문법 강제 `grammar`, 도구 줄이기 `toolFilterK`, 예시 `fewShot`). `thinking`은 보내지 않았습니다(모델 기본값)
- 반복: S0와 외부 기준은 3회, 장치를 하나씩 켠 것은 1회. 전부 켬은 3회 계획이었으나 1회에서 멈췄습니다(아래)

## 결과

| 변형 | 별칭 | 장치 | 반복 | 맞음(회차) | pass^k(항목) | 실행 오류(분모 제외) | 스키마 유효 | 되묻기 | 지연 p50/p95 | 모델 위치(회차) |
|---|---|---|---|---|---|---|---|---|---|---|
| S0 | `local` | 없음 | 3 | 135/180 (75.0%, 68.0%~81.1%) | pass^3 43/60 | 0/180 | 141/144 | 18/180 | 4.2s/8.8s | local 180 |
| 도구 줄이기 | `local` | toolFilterK 5 | 1 | 41/59 (69.5%, 56.1%~80.8%) | pass^1 41/59 | 1/60 | 43/43 | 7/59 | 4.3s/12.0s | local 59 |
| 예시 | `local` | fewShot | 1 | 50/58 (86.2%, 74.6%~93.9%) | pass^1 50/58 | 2/60 | 47/47 | 5/58 | 3.9s/8.3s | local 58 |
| 문법 강제 | `local-gguf` | grammar | 1 | 31/42 (73.8%, 58.0%~86.1%) | pass^1 31/42 | 18/60 | 28/28 | 7/42 | 9.9s/49.8s | local 42 |
| 전부 켬 | `local-gguf` | grammar + toolFilterK 5 + fewShot | 1 | 25/40 (62.5%, 45.8%~77.3%) | pass^1 25/40 | 20/60 | 24/24 | 7/40 | 8.3s/45.5s | local 40 |
| 외부 기준 | `external` | 없음 | 3 | 150/180 (83.3%, 77.1%~88.5%) | pass^3 48/60 | 0/180 | 143/143 | 9/180 | 1.5s/5.3s | external 117, local 63 |

- 맞음은 실행 오류를 분모에서 뺀 비율입니다. **문법 강제·전부 켬은 오류가 많아(18/60, 20/60) 맞음 비율을 그대로 비교하면 안 됩니다.** 오류는 모두 502(gateway LLM 504, 60초 제한)이고, 문법 강제는 도구 고르기와 인자 채우기를 두 번 부르는데 두 번째(구조화 출력) 호출이 자주 60초를 넘겼습니다.
- 외부 기준 180회차 중 63회차는 `local`로 처리됐습니다. 에이전트 모델 정책이 `local_only`인 에이전트(인사 등)는 외부 별칭을 요청해도 gateway가 로컬로 보내기 때문입니다. 각 실행 보고서의 "모델 위치별" 표에 나눠 적었습니다.
- 각 실행의 유형별·도구별·결과 분포·인자 틀림 목록은 같은 폴더의 실행별 `.md`에 있습니다.

## 실행 경위(측정에 넣지 않은 것)

- 감시 스크립트 실수로 문법 강제와 전부 켬 실행이 16:03~16:19에 겹쳐 돌았습니다. 그 두 실행은 버리고 다시 돌렸습니다.
- 전부 켬은 qwen 실행기 상주 메모리가 약 7GB로 늘어 WSL 메모리(12GB)를 다 써 OOM이 두 번 났습니다(부분 실행은 버림). 세 번째 시도는 1회차 60개를 마친 뒤 멈추고 그 1회를 결과로 씁니다(2회차 일부 14개는 버림).
- 장치를 하나씩 켠 local 묶음(S0, 도구 줄이기, 예시)은 각각 혼자 돌았습니다.

## 다시 재는 방법

```
cd eval
uv run python -m harness.cli toolcall-run --agent-url http://localhost:$PORT_AGENT --model local --variant '{}' \
  --repeats 3 --out reports/toolcall/<이름> --note "기기·모델 digest·Ollama 판"
uv run python -m harness.cli toolcall-report reports/toolcall/<이름>.json   # 기록을 지금 규칙으로 다시 채점
```
