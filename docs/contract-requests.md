
| 2026-11-21 | erp(incident) | #284 | `openapi/incident.yaml`(`POST /analyze`, 호스트 로컬 PORT_BASE + 70), tools.json `incident_analyze`(read, stage 2), scope `incident:read`, tools.schema backend.service·위임 토큰 aud에 `incident` | 장애 분석 도구 | 직접 PR, gateway #352, agent #353, ports.md는 리드 |
| 2026-11-21 | gateway | #384 | pack.yaml 선택 항목 `model_policy_override: local_only`(팩 단위 외부 LLM 금지), conditions.md에 모든 조건에서 켜짐 | #114 금융 팩 망분리 흉내 | contract/gateway-pack-local PR |
