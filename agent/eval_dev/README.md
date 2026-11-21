# 개발 묶음(도구 호출)

로컬 모델 도구 호출 측정(#103)의 개발 묶음 60개입니다. few-shot 예시와 프롬프트 다듬기에 씁니다. 확인 묶음(`tc-001`~`tc-120`)은 다른 작성자가 이 저장소의 구현을 보지 않고 따로 쓰며, 이 파일과 겹치지 않게 합니다.

## 형식

`tool_calls.jsonl`은 `contracts/eval/toolcall/`의 toolcall-v1 형식(`item.schema.json`)이고, 채점 규칙도 같은 폴더 README를 따릅니다.

- 번호는 확인 묶음과 겹치지 않게 `tc-901`~`tc-960`입니다
- 기준일은 모두 2027-03-10(수)입니다. 직원 ID는 팩 `fixtures/employees.json`, 회의실 ID는 `fixtures/rooms.json`입니다. 결재 문서·위임·예약·품목 번호는 가상 값이고 `setup`은 쓰지 않습니다
- 구성: direct 36, clarify 11, resolve 9, confusable 4. `targetTool`이 2단계 도구(`expense_request`, `purchase_request`)인 항목은 12개입니다
- 자유 문장 인자(`reason`, `title`, `purpose`, `question`, `q`)는 `argMatch: nonempty`, 발화에 나온 가맹점 이름은 `normalized`, 대결 기간은 `date`, 양식 목록은 `set`입니다
- 사유가 필수인 쓰기 도구는, 발화에 사유가 없으면 정답을 되묻기(`clarify`)로 둡니다(지어내지 않음)

`tests/test_eval_dev_set.py`가 형식, 팩·도구 계약(입력 스키마)과의 일치, 구매 합계(수량 × 단가)를 확인합니다.

## 경로 확인 실행

`smoke_run.py`는 이 묶음을 실제 agent 평가 경로(`POST /eval/tool-call`)로 한 번 돌립니다. 채점기가 아닙니다(채점·측정은 eval #237). 항목에 에이전트가 없어 `targetTool`을 가진 에이전트를 hr, assistant, finance, procurement 순으로 고릅니다.

```bash
uv run python eval_dev/smoke_run.py --url http://localhost:$PORT_AGENT \
  --out eval_dev/runs/<이름>.jsonl --model local --variant '{"thinking": false}'
```

기록은 `runs/`에 있습니다. 결과 줄에는 모델이 쓴 문장(`content`)이 들어 있습니다(가짜 데이터).

| 실행 | 조건 | 결과(60개, 1회) |
|---|---|---|
| `runs/2026-11-21-local-s0-nothink.jsonl` | 2026-11-21 00:17 KST. S0, `local`(qwen3.5:9b, digest d63f830f28d5, MLX 실행기), `thinking: false`, 온도 0. Ollama 0.40.15, Apple M1 Pro 32GB, 공용 Ollama(다른 세션 호출 있음) | HTTP 200 59개(1개는 agent LLM 시간 제한 60초 초과로 502). 첫 행동 이름 일치 24. 도구 호출이 정답인 48개 중 25개는 도구를 부르지 않고 확인·되묻기를 했습니다(그중 `asked` 판정은 7개). 되묻기 정답 11개 중 `asked` 판정 2개. 모델 호출 지연 p50 4.3초, p95 12.5초 |

이 실행에서 본 것(측정 결과가 아님, 판단은 eval이 함)
- 필요한 값이 모두 있어도 먼저 확인을 묻는 답이 많습니다(쓰기 도구에서 두드러짐). 선택 인자(`business_no`)를 필수처럼 묻기도 합니다.
- 되묻기 판정(마지막 줄이 물음 모양)은 "알려주시면 ~하겠습니다."로 끝나는 되묻기를 놓칩니다.

## 프롬프트 전후 비교(#305)

`first_call_run.py`는 업무 실행의 첫 계획 호출(S0, `/eval/tool-call`과 같은 코드)만 해서, 도구를 불렀는지·되물었는지·첫 도구 이름이 기대와 같은지만 셉니다. 서버 없이 모델 서버를 바로 부릅니다. 입력은 이 개발 묶음 60개와, eval 정상 셋 1단계 1회(#86) `full`에서 필수 도구를 부르지 않아 실패한 시나리오 25개의 첫 사용자 턴입니다(`runs/86-full-no-required-tool.ids`, 개발용으로만 씀). 정식 평가가 아니고, 시나리오는 첫 턴에 되묻는 것이 맞는 것도 있어(eval 하네스가 답함) 참고용입니다.

```bash
uv run python eval_dev/first_call_run.py --base-url http://<ollama>:11434/v1 --model qwen3.5:9b \
  --scenarios eval_dev/runs/86-full-no-required-tool.ids --out eval_dev/runs/<이름>.jsonl
```

조건: 2026-11-21 10:21~11:23 KST, 데스크탑 RTX 4070 SUPER, Ollama 0.40.15, `qwen3.5:9b`(GGUF Q4_K_M, digest 56671c2ab938, 문맥 4096), 온도 0, 생각 단계는 모델 기본값(켬), gateway 거치지 않음, 각 1회. 공용 Ollama라 다른 세션 호출과 겹쳤을 수 있습니다(지연은 참고만). 연결 오류는 3회까지 다시 부르고 줄에 `attempts`로 남깁니다.

| 프롬프트 | 개발 묶음: 기대 도구 호출(호출 정답 46) | 개발 묶음: 되묻기 정답 14에서 도구 없이 답함 | 시나리오 25: 도구를 부름 | 시나리오 25: requiredTools 중 하나를 부름 | 호출 지연 p50 |
|---|---|---|---|---|---|
| 전(`runs/2026-11-21-first-call-before.jsonl`) | 32 | 9 | 16 | 7 | 8.1초 |
| v1: 값이 다 있으면 바로 부름, 빠진 필수 값만 물음 (`…-after-v1.jsonl`) | 40 | 11 | 12 | 7 | 4.1초 |
| v2: v1 + 조회로 찾을 값은 먼저 조회, 하루짜리 휴가는 시작=종료, 공지·안내 문서도 policy_search (`…-after-v2.jsonl`) | 42 | 10 | 21 | 13 | 4.3초 |

- v1은 대결 상대·회수할 결재처럼 조회로 찾을 값을 사용자에게 물어 시나리오에서 나빠졌고, v2에서 다시 조회하게 됐습니다
- v2에서 되묻기 정답 항목 중 도구를 부른 4개는 모두 조회 도구였습니다(쓰기 도구를 지어 부른 경우 없음). 그중 정답이 되묻기뿐인 것은 `tc-925`("김 팀장님한테 결재 좀 맡겨 줘" → 직원 찾기) 하나입니다
- 정식 효과는 eval 정상 셋 실행으로 확인합니다


## 입구 라우터 비교(#303, 준비)

`router_compare.py`는 같은 입력을 라우터 방법마다 넣어 고른 에이전트·확률·지연을 줄로 남기고 간단히 셉니다(채점·보고는 eval). 어댑터는 `src/agent_runtime/decision_router.py`입니다.

- 입력: eval 정상 셋 80개의 첫 발화와 `expectedAgent`, 2단계 라우터 시험 문장 17개(`router_cases.jsonl`), "대결"을 "대리 결재"로 바꾼 변형. 확인 셋 원문은 쓰지 않습니다
- 방법: `keyword`(모델 없음), `llm`(지금 라우터, `--llm-base-url`), `laya`(로컬 인코더), `jev`(외부 API, `--allow-external`과 `TYPESAFE_API_KEY`가 있어야 돎. 지어낸 문장만 보냄)
- 집계: 정답 수(출처별), 인사·기밀(`local_only`) 요청을 외부 허용 에이전트로 보낸 수, 애매한 비율(LLM·키워드는 fallback, Laya는 `route=review`, Jev는 `confidence < --jev-threshold`)과 애매할 때 로컬로 보냈다면 남는 유출, 혼동, 지연 p50·p95, Jev 입력 토큰·비용(입력 100만 토큰당 0.042달러, 2026-11-21 docs.typesafe.ai)
- Laya 준비: `bash eval_dev/install_laya.sh`(laya 0.5.0, 가중치와 리비전 기록). agent 의존성에는 넣지 않고 `uv run --with laya==0.5.0 …`으로 얹습니다

```bash
uv run python eval_dev/router_compare.py --methods keyword --out eval_dev/runs/<이름>.jsonl
uv run --with laya==0.5.0 python eval_dev/router_compare.py --methods keyword,llm,laya --repeats 3 \
  --llm-base-url http://<ollama>:11434/v1 --llm-model qwen3.5:9b --out eval_dev/runs/<이름>.jsonl
```

키워드만 먼저 돌린 결과(2026-11-21, 105문장 1회): 정답 89(정상 셋 69/80, 변형 5/8, 2단계 문장 15/17), `local_only` 요청을 외부 허용 에이전트로 보낸 수 10, 모두 fallback(애매)이라 fallback 대화를 로컬로 실행하면(#308) 0.
