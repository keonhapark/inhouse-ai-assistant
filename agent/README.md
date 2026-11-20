# agent

에이전트 등록부 런타임과 입구 라우터입니다. API는 `contracts/openapi/agent.yaml`을 따릅니다.

- `GET /agents`: `PACK_DIR`의 `agents.yaml`에서 팩 단계(`pack.yaml`의 `stage`) 이하로 켜진 에이전트를 돌려줍니다.
- `POST /route`: 요청을 에이전트 하나에 한 번만 넘깁니다.
  - `method: llm`(기본): 등록부의 설명·예시를 프롬프트에 넣고 모델이 하나를 고릅니다. 모델 호출은 gateway의 OpenAI 호환 엔드포인트로 합니다.
  - `method: keyword`: `routing.keywords`가 가장 많이 든 에이전트를 고르는 기준선입니다. 비교 평가에 씁니다.
  - 고르지 못하면(맞는 것 없음, 동점, 확신도 미달, 모델 오류) `fallback_agent`가 받습니다. 고른 에이전트를 요청자가 부를 수 없으면(`callable_by`) 역시 `fallback_agent`가 받고, 고른 에이전트는 `suggestedAgentId`로 안내만 합니다.
  - 결정마다 감사 이벤트 `route.decided`를 JSON Lines로 남깁니다. 요청 원문과 모델이 쓴 이유 문장은 감사 기록에 넣지 않습니다.

업종 용어(부서·에이전트 이름)는 코드에 두지 않고 모두 팩에서 읽습니다.

## 실행

```bash
cd agent
uv sync
PACK_DIR=../packs/manufacturing uv run uvicorn --factory agent_runtime.app:create_app --port 8320
```

| 환경 변수 | 기본값 | 뜻 |
|---|---|---|
| `PACK_DIR` | (필수) | 업종 팩 폴더 |
| `AGENT_AUDIT_LOG` | `var/audit.jsonl` | 감사 이벤트 파일 |
| `AGENT_ROUTER_MIN_CONFIDENCE` | `0.5` | LLM 라우터 확신도가 이보다 낮으면 fallback |
| `AGENT_LLM_BACKEND` | `gateway` | `gateway` 또는 `ollama`(gateway가 없을 때 쓰는 개발용) |
| `GATEWAY_LLM_URL` | `http://localhost:$PORT_GATEWAY/v1` | gateway의 OpenAI 호환 엔드포인트 |
| `AGENT_OLLAMA_BASE_URL` | `http://localhost:11434` | 개발용 Ollama 주소 |
| `AGENT_LLM_MODEL` | `LOCAL_MODEL` 또는 `qwen3.5:9b` | 모델 이름 |

## 시험

```bash
cd agent
uv run pytest -q
```

LLM 라우터 시험은 `tests/recordings/router_llm.json`에 녹화한 모델 응답으로 돕니다. 녹화본에 없는 요청이 오면 실패합니다. 프롬프트나 등록부를 바꿨으면 다시 녹화합니다.

```bash
AGENT_LLM_RECORD=1 AGENT_LLM_BACKEND=ollama AGENT_LLM_CALL_BUDGET=20 uv run pytest -q tests/test_router.py
```

녹화 때 실제 호출은 시험 세션 하나에서 `AGENT_LLM_CALL_BUDGET`(기본 40)번까지만 합니다. 로컬 모델을 여러 작업이 같이 쓰기 때문입니다.
