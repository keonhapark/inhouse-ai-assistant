# MCP 도구 계약

도구 목록과 입력·출력은 `tools.json`(형식 `tools.schema.json`)입니다.

## 요청 `_meta`

agent MCP 서버는 도구 인자와 별도로 MCP 요청의 `_meta`에서 아래 값을 받습니다. 도구 인자에 넣지 않는 것은 LLM이 고를 수 없게 하려는 것입니다. 실행기(LangGraph)가 채웁니다.

| 키 | 형식 | 뜻 |
|---|---|---|
| `dryRun` | boolean | 쓰기 도구를 미리보기로 부릅니다(erp `?dryRun=true`) |
| `idempotencyKey` | string | 쓰기 실행의 멱등 키(erp `Idempotency-Key`). 미리보기에서 실행으로 넘어갈 때 새로 만듭니다 |
| `trustLevel` | `user_direct` \| `trusted` \| `untrusted` | 이 호출을 이끈 입력의 신뢰 등급. `user_direct`를 요구하는 도구는 그 밖의 등급이면 거절합니다 |

위임 토큰은 HTTP 헤더로 받습니다.
