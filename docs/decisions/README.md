# 결정 기록

`NNNN-<주제>.md`에 결정, 고른 이유, 버린 대안, 정한 사람을 적습니다.

## 사용자가 정할 설계 지점(기획서 5-7)

초안은 계약에 들어가 있고, 사용자가 고르면 결정 기록으로 남깁니다.

| 지점 | 초안 위치 | 상태 |
|---|---|---|
| 위험 등급 표 | `contracts/mcp/tools.json`의 `risk`, `packs/manufacturing/agents.yaml`의 `risk_policy` | 확정(0003) |
| 신뢰 등급 표 | `contracts/mcp/tools.json`의 `trust_required`, `packs/manufacturing/docs.yaml`의 `trust` | 확정(0003) |
| 감사 스키마 필드 | `contracts/events/audit.schema.json` | 확정(0003) |
| 되돌리기 충돌 의미 | `contracts/openapi/erp.yaml`의 각 쓰기 `x-undo` | 확정(0003) |
| 사고 판정 규칙 | `contracts/eval/scenario.schema.json`의 `expect` | 확정(0003) |
| 대결 규칙(범위 단위, 금액 한도, 등록 승인 기준) | `packs/manufacturing/org.yaml`의 `delegation_policy` | 확정(0003) |

## 기록

| 번호 | 주제 | 정한 사람 |
|---|---|---|
| 0001 | 모듈 세션이 자기 PR을 병합 | 사용자 |
| 0002 | 1단계 평가를 정상 셋 세 조건 한 번으로 | 사용자 |
| 0003 | 설계 지점 6개를 초안대로 | 사용자 |
| 0004 | 신뢰할 수 없는 글을 읽은 대화는 끝까지 실행 전 확인 | 프로젝트 리드, 사용자 확인 |
| 0005 | 고치는 데 쓴 정상 셋은 2단계부터 개발 셋으로 표시, 보호 지표는 정상 셋 v2 | 프로젝트 리드 |
| 0006 | 평가 승인자는 요청자 의도 모형, full은 항상 승인으로도 함께 냄 | 프로젝트 리드, 사용자 확인 |
| 0007 | 2단계 확인 셋·도구 호출 확인 묶음은 1회 결과로 내고 반복은 뒤로 | 사용자 |
