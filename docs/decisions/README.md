# 결정 기록

`NNNN-<주제>.md`에 결정, 고른 이유, 버린 대안, 정한 사람을 적습니다.

## 사용자가 정할 설계 지점(기획서 5-7)

초안은 계약에 들어가 있고, 사용자가 고르면 결정 기록으로 남깁니다.

| 지점 | 초안 위치 | 상태 |
|---|---|---|
| 위험 등급 표 | `contracts/mcp/tools.json`의 `risk`, `packs/manufacturing/agents.yaml`의 `risk_policy` | 초안 |
| 신뢰 등급 표 | `contracts/mcp/tools.json`의 `trust_required`, `packs/manufacturing/docs.yaml`의 `trust` | 초안 |
| 감사 스키마 필드 | `contracts/events/audit.schema.json` | 초안 |
| 되돌리기 충돌 의미 | `contracts/openapi/erp.yaml`의 각 쓰기 `x-undo` | 초안 |
| 사고 판정 규칙 | `contracts/eval/scenario.schema.json`의 `expect` | 초안 |
| 대결 규칙(범위 단위, 금액 한도, 등록 승인 기준) | `packs/manufacturing/org.yaml`의 `delegation_policy` | 초안 |

## 기록

| 번호 | 주제 | 정한 사람 |
|---|---|---|
| 0001 | 모듈 세션이 자기 PR을 병합 | 사용자 |
