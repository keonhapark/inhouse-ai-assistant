# 입구 라우터 비교: LLM·키워드·Laya(#303)

입구 라우터가 요청을 맞는 부서 에이전트로 넘기는지, 지금 LLM 라우터(로컬 qwen3.5:9b)와 키워드 기준선과 Laya(결정 전용 인코더, 로컬)를 같은 문장으로 견줍니다. 실측은 agent가 했고(#376, `agent/eval_dev/runs/`), 이 보고서의 수치는 eval이 그 줄 기록을 다시 세어 낸 것입니다(`eval/tools/router_report.py`). 3단계 등록부 문장은 #492 녹화본 시험 결과입니다.

**탐색입니다.** 정상 셋 v1은 #304·#305·#308·#317을 만들 때 본 셋이라(결정 0005) 이 비교도 보호 지표가 아닙니다. Jev(외부 API)는 사용자 결정으로 뺐습니다(같은 계열 오픈소스인 Laya가 이 라우팅에 맞지 않아 비교 가치가 낮음).

## 조건(#376 기록)

- 문장 105개 × 3회: 정상 셋 v1 80개의 첫 발화와 정답 에이전트, "대결"을 "대리 결재"로 바꾼 변형 8개, 2단계 라우터 시험 문장 17개. 확인 셋 원문은 쓰지 않았습니다.
- llm: 데스크탑 RTX 4070 SUPER, Ollama 0.40.15 `qwen3.5:9b`(digest 56671c2ab938)를 gateway 없이 바로 부름, 생각 단계 기본값(운영과 같음), 온도 0. 공용 모델 서버였어서 지연은 참고만 합니다.
- Laya: laya 0.5.0, CPU(torch 2.15.0+cpu, `OMP_NUM_THREADS=8`). 선택지 구성 세 가지(키워드 목록, 설명만, 설명+예시)를 모두 남겼습니다. 구성은 40문장 표본으로 먼저 견줘 보고 정했습니다.
- 유출로 이어지는 오분류: 정답 에이전트가 `local_only`(hr·finance·it_ops·rnd)인데 `external_allowed`(assistant·procurement·quality·sales)로 보낸 줄입니다(`packs/manufacturing/agents.yaml`).
- 애매: LLM·키워드는 기본 에이전트로 간 줄, Laya는 확신도 0.5 미만인 줄입니다.

## 결과(줄 = 문장 × 반복, 315줄)

| 방법(기록) | 정답(줄) | 정상 셋 | "대리 결재" 변형 | 2단계 문장 | 세 번 모두 맞은 문장 | 반복 간 다른 문장 | `local_only`→외부 허용 | 애매 | 애매를 로컬로 보내면 남는 유출 | 지연 p50 / p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| llm(`2026-11-21-router-llm.jsonl`) | 284/315 (90.2%, 86.3%~93.2%) | 217/240 | 16/24 | 51/51 | 93/105 | 4 | 4 | 2 | 3 | 13.02초 / 31.43초 |
| keyword(`2026-11-21-router-keyword.jsonl`) | 267/315 (84.8%, 80.3%~88.5%) | 207/240 | 15/24 | 45/51 | 89/105 | 0 | 30 | 45 | 0 | 0.00초 / 0.00초 |
| laya-cpu-desc(`2026-11-21-router-laya-cpu-desc.jsonl`) | 174/315 (55.2%, 49.6%~60.8%) | 120/240 | 12/24 | 42/51 | 58/105 | 0 | 24 | 159 | 0 | 0.27초 / 0.34초 |
| laya-cpu-desc_examples(`2026-11-21-router-laya-cpu-desc_examples.jsonl`) | 45/315 (14.3%, 10.6%~18.6%) | 21/240 | 0/24 | 24/51 | 15/105 | 0 | 0 | 39 | 0 | 0.30초 / 0.45초 |
| laya-cpu-keywords(`2026-11-21-router-laya-cpu-keywords.jsonl`) | 231/315 (73.3%, 68.1%~78.1%) | 177/240 | 12/24 | 42/51 | 77/105 | 0 | 18 | 99 | 6 | 0.24초 / 0.31초 |

오분류(정답→고른 것, 많은 순 다섯):

- llm: assistant→hr 22, hr→assistant 4, hr→finance 3, assistant→finance 2
- keyword: hr→assistant 24, assistant→hr 18, finance→assistant 3, it_ops→assistant 3
- laya-cpu-desc: assistant→finance 27, assistant→it_ops 21, assistant→hr 21, hr→it_ops 18, hr→finance 15
- laya-cpu-desc_examples: hr→finance 147, assistant→finance 93, assistant→procurement 12, procurement→finance 9, it_ops→finance 6
- laya-cpu-keywords: hr→it_ops 24, assistant→hr 15, hr→assistant 12, hr→finance 12, assistant→it_ops 9

짝 비교(같은 문장·반복, llm − 다른 방법, Newcombe 95%):

- llm − keyword: +5.4%p (+1.5~+9.4%p, 짝 315)
- llm − laya-cpu-desc: +34.9%p (+28.6~+40.9%p, 짝 315)
- llm − laya-cpu-desc_examples: +75.9%p (+70.5~+80.0%p, 짝 315)
- llm − laya-cpu-keywords: +16.8%p (+11.5~+22.2%p, 짝 315)
지연 p95는 eval의 백분위 계산(순위 방식)이라 agent 기록 표(30.8초)와 조금 다릅니다.

## 읽는 법

- **LLM 라우터가 가장 맞습니다.** 90.2%로 키워드보다 5.4%p(+1.5~+9.4%p), Laya 최선 구성(키워드 목록)보다 16.8%p 높습니다. 2단계 문장은 51/51입니다.
- **유출로 이어지는 오분류는 LLM 4줄, 키워드 30줄입니다.** LLM의 4줄 중 3줄은 확신도가 높아 애매로 잡히지 않아, "애매하면 로컬로" 규칙으로는 막히지 않습니다. 키워드는 애매(기본 에이전트) 45줄을 로컬로 보내면 유출이 0이 되지만 정답률이 낮습니다.
- **LLM 오분류는 대부분 `assistant`↔`hr`입니다**(assistant→hr 22, hr→assistant 4). 회의실·규정 안내 요청을 인사로 보내는 쪽(로컬로 가므로 유출은 아님)이 많습니다.
- **"대리 결재" 변형은 모든 방법에서 원문보다 정답이 줄었습니다**(LLM 16/24). 용어가 라우팅에 영향을 줍니다.
- **Laya는 이 라우팅에 맞지 않았습니다.** 선택지 구성에 따라 14~73%로 크게 흔들렸고, 설명+예시 구성은 거의 모두 재무로 골랐습니다(이 구성의 유출 0은 재무로만 보낸 결과). 지연은 0.3초 안팎으로 빠릅니다.
- **반복 간 안정성:** LLM은 105문장 중 4문장이 반복마다 달랐고, 키워드·Laya는 같았습니다.

## 3단계 등록부 문장(#492)

품질·연구소·영업이 더해진 등록부에서 16문장(부를 수 없는 에이전트는 안내, 요청 안의 "연구소로 넘겨" 같은 지시는 따르지 않음, 앞 단계 에이전트 포함)을 코랩 T4 `qwen3.5:9b`(생각 끔) 녹화본으로 시험했습니다. LLM 15/16, 키워드 15/16입니다. LLM의 1건은 "수입 검사 부적합 처리 절차" 질문에 품질·구매 둘 다 가능하다며 에이전트를 고르지 않은 것으로, 시험에 알려진 오답으로 남겼습니다(`agent/tests/test_router_stage3.py`). 녹화본이라 지연·반복 변동은 재지 않았습니다.

## 다시 재는 방법

```
cd agent   # 실측(agent/eval_dev/README.md "입구 라우터 비교")
uv run python eval_dev/router_compare.py --methods llm --repeats 3 --llm-base-url http://<ollama>:11434/v1 --llm-model qwen3.5:9b --out eval_dev/runs/<이름>.jsonl
cd ../eval # 다시 세기
uv run python tools/router_report.py --runs ../agent/eval_dev/runs --pack ../packs/manufacturing
cd ../agent && uv run pytest tests/test_router_stage3.py -s   # 3단계 녹화본
```
