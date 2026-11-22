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

## 생각 단계 끔·켬 비교(#423)

#424는 여러 턴 대화의 시간 초과를 막으려고 업무 실행의 로컬 계획 호출에 `reasoning_effort: none`(생각 끔)을 보냅니다. 같은 입력(개발 묶음 60 + 시나리오 25)과 같은 코드로 생각만 바꿔(끔, `low`, 모델 기본값) 첫 계획 호출을 비교했습니다. 프롬프트는 #429(날짜·선택 항목 안내)가 들어간 develop 기준입니다.

```bash
uv run python eval_dev/first_call_run.py --base-url <모델 서버>/v1 --model qwen3.5:9b \
  --scenarios eval_dev/runs/86-full-no-required-tool.ids --variant '{"thinking": false}' \
  --out eval_dev/runs/<이름>.jsonl   # low는 '{"thinking": true}', 모델 기본값은 --variant 없이
```

조건: 2026-11-22 06:12~07:36 KST(끔 06:12, 기본값 06:18, low 07:05 시작), 코랩 T4, Ollama 0.40.17, `qwen3.5:9b`(GGUF Q4_K_M, digest 56671c2ab938, 문맥 8192), 온도 0, 각 1회. Cloudflare 터널을 거쳐 지연에 왕복 시간이 들어 있어 데스크탑보다 크고, 앞 절(데스크탑 RTX 4070 SUPER, 문맥 4096)과 기기가 달라 지연은 앞 절과 비교하지 않습니다. 오류는 3회까지 다시 부른 뒤에도 실패한 줄입니다.

| 생각 | 개발 묶음: 기대 도구 호출(호출 정답 46) | 개발 묶음: 되묻기 정답 14에서 도구 없이 답함 | 시나리오 25: 도구를 부름 | 시나리오 25: requiredTools 중 하나를 부름 | 호출 지연 p50 / p95 / 최대 | 오류 |
|---|---|---|---|---|---|---|
| 끔(`runs/2026-11-22-first-call-colab-nothink.jsonl`) | 28 | 12 | 12 | 5 | 3.1초 / 5.2초 / 6.9초 | 0 |
| low(`runs/2026-11-22-first-call-colab-think-low.jsonl`) | 43 | 10 | 21 | 12 | 10.2초 / 25.8초 / 48.3초 | 2(터널 524) |
| 켬, 모델 기본값(`runs/2026-11-22-first-call-colab-think-default.jsonl`) | 44 | 9 | 20 | 11 | 10.3초 / 22.4초 / 31.7초 | 3(터널 524, 100초 초과) |

- 생각을 끄면 지연은 약 3분의 1이 되지만, 호출이 정답인 46개 중 17개에서 도구를 부르지 않았습니다. 그중 물음으로 끝난 것은 6개이고, 나머지는 "dlg-0031을 해지하겠습니다."처럼 하겠다고만 하거나, 다 있는 값을 확인해 달라고 하거나, 조회 도구가 있는데 조회할 수 없다고 답했습니다
- 생각을 켜면 도구를 부르지 않은 것은 1개(물음)였고, 100초를 넘긴 3개(`tc-937`, `tc-957`, 시나리오 1개)는 터널 시간 제한에 걸렸습니다. agent의 LLM 시간 제한 60초를 넘긴 줄은 없었습니다(성공한 82개 중 최대 31.7초)
- `low`는 기본값과 정확도·지연이 거의 같았습니다. 이 서버(Ollama 0.40.17, qwen3.5:9b)에서는 `low`가 생각 길이를 줄이지 못했습니다. 524 2개는 `tc-902`, `tc-957`입니다
- 업무 실행에서 생각 끔(#424)을 유지할지, 첫 계획 호출만 켜는 방식 등으로 바꿀지는 이 비교로 정하지 않습니다. 결정은 이슈 #423에서 리드·사용자가 합니다


## 입구 라우터 비교(#303, 준비)

`router_compare.py`는 같은 입력을 라우터 방법마다 넣어 고른 에이전트·확률·지연을 줄로 남기고 간단히 셉니다(채점·보고는 eval). 어댑터는 `src/agent_runtime/decision_router.py`입니다.

- 입력: eval 정상 셋 80개의 첫 발화와 `expectedAgent`, 2단계 라우터 시험 문장 17개(`router_cases.jsonl`), "대결"을 "대리 결재"로 바꾼 변형. 확인 셋 원문은 쓰지 않습니다
- 방법: `keyword`(모델 없음), `llm`(지금 라우터, `--llm-base-url`), `laya`(로컬 인코더), `jev`(외부 API, `--allow-external`과 `TYPESAFE_API_KEY`가 있어야 돎. 지어낸 문장만 보냄)
- 집계: 정답 수(출처별), 인사·기밀(`local_only`) 요청을 외부 허용 에이전트로 보낸 수, 애매한 비율(LLM·키워드는 fallback, Laya·Jev는 `confidence < --decision-threshold`(기본 0.5, laya 0.5.0 답에는 `route`가 없음))과 애매할 때 로컬로 보냈다면 남는 유출, 혼동, 지연 p50·p95, Jev 입력 토큰·비용(입력 100만 토큰당 0.042달러, 2026-11-21 docs.typesafe.ai)
- Laya 준비: `bash eval_dev/install_laya.sh`(laya 0.5.0, torch CPU 판, 저장소 밖 가상환경 `~/.cache/iaa-laya-venv`에 laya와 agent를 넣고 가중치와 리비전을 `runs/laya-install.json`에 기록). agent 의존성(uv.lock)에는 넣지 않습니다

```bash
uv run python eval_dev/router_compare.py --methods keyword --out eval_dev/runs/<이름>.jsonl
uv run python eval_dev/router_compare.py --methods llm --repeats 3 \
  --llm-base-url http://<ollama>:11434/v1 --llm-model qwen3.5:9b --out eval_dev/runs/<이름>.jsonl
CUDA_VISIBLE_DEVICES= ~/.cache/iaa-laya-venv/bin/python eval_dev/router_compare.py --methods laya --repeats 3 \
  --out eval_dev/runs/<이름>.jsonl
```

### 실측(2026-11-21, 105문장 × 3회, Jev 제외)

조건: 데스크탑. llm은 RTX 4070 SUPER의 Ollama 0.40.15 `qwen3.5:9b`(GGUF Q4_K_M, digest 56671c2ab938)를 바로 부름(gateway 거치지 않음, 생각 단계 기본값=운영과 같음, 온도 0), 14:19~15:33. Laya는 GPU를 평가 측정이 써서 CPU(torch 2.15.0+cpu, `OMP_NUM_THREADS=8`), laya 0.5.0, 모델 리비전 `runs/laya-install.json`. 공용 모델 서버라 llm 지연은 참고만 합니다. 문장: 정상 셋 80, "대리 결재" 변형 8, 2단계 문장 17.

| 방법 | 정답(315) | 정상 셋(240) | 변형(24) | 2단계(51) | 세 번 모두 맞은 문장(105) | `local_only`→외부 허용 | 애매(기준) | 애매를 로컬로 보내면 남는 유출 | 지연 p50 / p95 |
|---|---|---|---|---|---|---|---|---|---|
| llm(`runs/2026-11-21-router-llm.jsonl`) | 284 | 217 | 16 | 51 | 93 | 4 | 2(fallback) | 3 | 13.0초 / 30.8초 |
| keyword(`…-router-keyword.jsonl`) | 267 | 207 | 15 | 45 | 89 | 30 | 45(fallback) | 0 | 0 |
| Laya 키워드 목록(`…-laya-cpu-keywords.jsonl`) | 231 | 177 | 12 | 42 | 77 | 18 | 99(confidence<0.5) | 6 | 0.24초 / 0.31초 |
| Laya 설명만(`…-laya-cpu-desc.jsonl`) | 174 | 120 | 12 | 42 | 58 | 24 | 159 | 0 | 0.27초 / 0.34초 |
| Laya 설명+예시(`…-laya-cpu-desc_examples.jsonl`) | 45 | 21 | 0 | 24 | 15 | 0 | 39 | 0 | 0.30초 / 0.45초 |

- llm은 반복 간 결과가 다른 문장이 4/105이고, Laya·keyword는 반복마다 같습니다
- llm 오분류는 대부분 `assistant` ↔ `hr`(`assistant->hr` 22, `hr->assistant` 4)입니다. `local_only` 요청을 외부 허용 에이전트로 보낸 4건 중 3건은 확신도가 높아 애매로 잡히지 않습니다
- Laya는 선택지 구성에 따라 크게 달랐습니다. 설명+예시(LLM 라우터와 같은 정보)에서는 거의 모두 재무로 골랐고(선택지 한도 `head_max_len`을 1024로 올려도 같음), 이 구성의 유출 0은 재무로만 보낸 결과입니다. 구성은 40문장 표본으로 먼저 견줘 보고 정해, 셋을 모두 남깁니다
- "대리 결재" 변형은 모든 방법에서 원문보다 정답이 줄었습니다
- 판단과 보고는 eval이 합니다(#303). Jev는 외부 전송이라 사용자 확인 뒤에 돌립니다

## 이미지 읽기 실측(#382)

`vision_read_run.py`는 업무 실행과 같은 읽기 코드(`run/image_reading.py`의 `ImageReader.read`: 팩 `image_reading` 항목, json_schema 출력, 생각 끔)로 그림을 읽고, eval 채점기(`eval/harness/vision.py`의 `score`)로 셉니다. 도면은 제조 팩 `rnd`, 불량 사진은 `quality` 에이전트의 읽을 항목을 씁니다. gateway·라우터·대화는 거치지 않고 모델 서버(OpenAI 호환)를 바로 부르므로, 대화 경로 전체를 보는 eval `vision-run`과는 다릅니다. 읽은 값을 줄마다 이어 붙인 글을 답 본문으로 채점합니다.

```bash
cd eval && for l in 1 2 3; do uv run --group tools python tools/make_images.py --level $l --drawings 20 --out <저장소 밖>/l$l; done
cd ../agent && uv run python eval_dev/vision_read_run.py read --base-url <모델 서버>/v1 --model qwen3.5:9b-q4_K_M \
  --images <저장소 밖>/l1 --images <저장소 밖>/l2 --images <저장소 밖>/l3 --out eval_dev/runs/<이름>.jsonl
cd ../eval && uv run python ../agent/eval_dev/vision_read_run.py score ../agent/eval_dev/runs/<이름>.jsonl
```

조건: 2026-11-22 09:33~09:41 KST, 코랩 T4, Ollama 0.40.17, `qwen3.5:9b-q4_K_M`(local-vision과 같은 가중치, digest 56671c2ab938, 문맥 8192), 온도 0, 각 1회. Cloudflare 터널을 거쳐 지연에 왕복 시간이 들어 있습니다. local-vision은 LiteLLM `ollama_chat`(네이티브 API)으로 부르고 이 측정은 OpenAI 호환 경로라 출력 형식 지정 방식이 다릅니다. 그림은 `make_images.py` 개발 시드 7(1단계 20장의 앞 5장은 커밋한 `images/`와 같음, 20번째와 불량 사진 2장은 숨은 지시 그림), 기록은 `runs/2026-11-22-vision-read-colab.jsonl`입니다.

| 그림 | 장(숨은 지시 제외) | 읽지 못함 | 모두 맞음 | 부품 번호·품목 코드 | 도면 이름·불량 유형 | 치수·주기 | 지연 p50 / 최대 |
|---|---|---|---|---|---|---|---|
| 도면 1단계 | 19 | 0 | 19 | 19 | 19 | 114/114 | 7.7초 / 7.9초 |
| 도면 2단계 | 20 | 0 | 20 | 20 | 20 | 120/120 | 7.6초 / 7.8초 |
| 도면 3단계 | 20 | 0 | 19 | 20 | 20 | 119/120 | 7.9초 / 8.0초 |
| 합성 불량 사진 | 2 | 0 | 2 | 2 | 2 | - | 5.4초 / 5.6초 |

- 도면 OCR+BM25 기준선(eval `reports/vision/2026-11-22-drawing-levels.md`, 60장)이 2·3단계에서 "끝까지 모두 맞음" 12/60·2/60으로 떨어진 것과 달리, 비전 모델은 단계가 올라가도 거의 다 읽었습니다. 다만 과제가 다릅니다(기준선은 질의로 도면을 찾아 치수를 답하고, 여기서는 그림 한 장을 받아 항목을 읽음)
- 3단계에서 틀린 하나는 `dwg-l3-007`의 `DIA 35 h7`을 `DIA 36 h7`로 읽은 것입니다
- 2단계의 비슷한 부품 번호("REPLACES", 한 자리 다름)를 부품 번호로 잘못 읽은 것은 없었습니다
- 숨은 지시 그림 3장: 도면은 지시 글을 항목에 넣지 않고 다른 도면처럼 읽었습니다(출력 항목이 스키마로 정해져 있음). 불량 사진 2장의 심각도는 `minor`였는데, 지시가 없는 불량 사진 2장도 `minor`라 지시를 따랐는지는 이 측정으로 가릴 수 없습니다. 지시를 따랐는지는 eval 시나리오(`dev-s3-inject-*`)가 봅니다
- 합성 그림은 깨끗한 내장 글꼴이라 실제 도면·현장 사진보다 쉽습니다. 실제 불량 사진(VisA)은 이 측정에 넣지 않았습니다

## 영수증·VisA 불량 사진 비전 실측(#549)

`vision_bench.py`는 업무 실행과 같은 읽기 코드(`ImageReader.read`, json_schema 출력, 생각 끔)로 그림을 읽고 eval 채점기로 셉니다. 모델 서버를 바로 부르고 gateway·라우터·대화는 거치지 않습니다(#521과 같은 방식). 명령은 파일 머리말에 있습니다.

- 영수증: eval 가짜 영수증 개발 묶음 40장(#462, `~/data/receipts-dev`, Noto Sans KR). 읽을 항목은 제조 팩 경비 에이전트의 `image_reading`(금액·사용일·가맹점·사업자번호) 그대로이고 채점은 `eval/harness/receipts.py`(필드 완전 일치, 표기 정규화)
- VisA: candle·pcb1 부분집합(#509, CC BY 4.0). CPU 기준선과 같은 시험 절반(기준선 결과 JSON `eval/reports/vision/2026-11-22-visa-baseline-candle-pcb1.json`의 이상 탐지 과제 사진 80장 = 정상 40·불량 40)을 쓰고, 기준선 1-NN처럼 범주의 불량 유형 목록(candle 7, pcb1 4)과 none 중에서 고르게 했습니다(닫힌 선택, 업무 팩의 자유 서술 항목과 다름). 한 번 호출로 불량 여부와 유형을 함께 읽습니다

조건: 2026-11-22 19:48~20:00 KST, Kaggle T4, 터널 경유(지연에 왕복 포함), Ollama 0.40.17, `qwen3.5:9b-q4_K_M`(local-vision과 같은 가중치, digest 56671c2ab938), 온도 0, 각 1회. 기록은 `runs/2026-11-22-vision-receipts-kaggle.jsonl`, `runs/2026-11-22-vision-visa-kaggle.jsonl`입니다. 구간은 Clopper-Pearson 95%입니다.

| 영수증(40장) | 비전 모델 | 기준선 RapidOCR+정규식(#508) |
|---|---|---|
| 네 필드 모두 | 24/40 (60.0%, 43.3%~75.1%) | 24/40 (60.0%, 43.3%~75.1%) |
| 금액 | 27/40 | 38/40 |
| 날짜 | 36/40 | 35/40 |
| 가맹점 | 37/40 | 27/40 |
| 사업자번호 | 38/40 | 39/40 |
| 한 장 지연 p50 | 3.8초(T4, 터널) | 0.96초(CPU OCR) |

| VisA(시험 80장) | 비전 모델 | 기준선 손 특징+1-NN(#509) |
|---|---|---|
| 불량 유형(불량 40장) | 14/40 (35.0%, 20.6%~51.7%) | 19/40 (47.5%, 31.5%~63.9%) |
| 　candle / pcb1 | 11/20 / 3/20 | 9/20 / 10/20 |
| 이상 탐지 재현율 | 22/40 (55.0%, 38.5%~70.7%) | 17/40 (42.5%, 27.0%~59.1%) |
| 이상 탐지 거짓 경보 | 0/40 (0.0%, 0.0%~8.8%) | 5/40 (12.5%, 4.2%~26.8%) |
| 이상 탐지 정확도 | 62/80 (77.5%, 66.8%~86.1%) | 52/80 (65.0%, 53.5%~75.3%) |
| 한 장 지연 p50 | 6.8초(T4, 터널) | 전체 5.4초(CPU) |

- **영수증은 네 필드 모두 맞은 수가 기준선과 같고(24/40), 틀리는 곳이 다릅니다.** 비전 모델은 가맹점(37 vs 27)이 낫고 금액(27 vs 38)이 나쁩니다. 금액 오답 13장은 모두 정답보다 큰 값이고 11장이 카드 전표입니다. 그중 5장은 정확히 합계(부가세 포함)에 부가세를 한 번 더 더한 값입니다. 개발 묶음이라 읽기 프롬프트는 고치지 않았습니다
- **VisA는 이상 탐지가 기준선보다 낫고(정확도 77.5% vs 65.0%, 거짓 경보 0), 불량 유형은 낮습니다(35.0% vs 47.5%).** 유형은 pcb1이 특히 낮습니다(3/20). 기준선은 같은 범주의 학습 절반 사진으로 1-NN을 하고, 비전 모델은 유형 이름만 보고 고릅니다(예시 사진 없음)
- 각 1회, 40장·80장이라 구간이 넓고, 영수증 네 필드 모두와 VisA 유형은 구간이 겹칩니다
