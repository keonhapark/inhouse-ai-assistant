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

## 팩 양식 도구

새 업종 팩의 결재 양식을 올리는 도구는 공용 `tools.json`에 더하지 않고 팩 `forms.yaml` 양식의 `tool` 항목으로 정합니다(#397). agent MCP 카탈로그와 gateway(위임 토큰의 `tools`·`scopes` 계산)는 아래 규칙으로 같은 도구를 만들어 공용 도구와 똑같이 다룹니다. 참조 구현은 `contracts/tools/pack_tools.py`입니다.

| 도구 항목 | 값 |
|---|---|
| `name`, `description` | 양식 `tool`의 값. 공용 `tools.json`·같은 팩의 다른 양식 도구와 겹치면 안 됨 |
| `inputSchema` | 양식 `fields`(JSON Schema)에서 `x-`로 시작하는 키를 뺀 것 |
| `risk` | `tool.risk`, 없으면 `reversible_write`(올린 결재는 회수할 수 있음) |
| `trust_required` | `tool.trust_required`, 없으면 `user_direct` |
| `required_scope` | `approval:request:<양식 id>` |
| `backend` | erp `createApprovalDocument`, `fixed: {formId: <양식 id>}` |
| `stage` | `tool.stage`, 없으면 양식 `stage` |

- 공용 `tools.json` 도구가 이미 올리는 양식(`fixed.formId`가 같은 것)에는 `tool`을 둘 수 없습니다(제조 팩 leave·expense·purchase는 공용 그대로).
- 위험 정책·신뢰 등급·등록부·라우터는 공용 도구와 같은 방식으로 다룹니다. `tools/check_packs`가 이름 겹침과 에이전트 참조를 검사합니다.
