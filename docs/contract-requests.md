
| 2026-11-21 | erp(incident) | #284 | `openapi/incident.yaml`(`POST /analyze`, 호스트 로컬 PORT_BASE + 70), tools.json `incident_analyze`(read, stage 2), scope `incident:read`, tools.schema backend.service·위임 토큰 aud에 `incident` | 장애 분석 도구 | 직접 PR, gateway #352, agent #353, ports.md는 리드 |
| 2026-11-21 | gateway | #384 | pack.yaml 선택 항목 `model_policy_override: local_only`(팩 단위 외부 LLM 금지), conditions.md에 모든 조건에서 켜짐 | #114 금융 팩 망분리 흉내 | contract/gateway-pack-local PR |
| 2026-11-21 | web | #385 | agent `ToolPreview.fromAttachments`, gateway ChatEvent `approval.fromAttachments`, 대화 기록 `user_message.attachments[]`(`AttachmentMeta`, 본문 없음) | 채팅 이미지 첨부 화면의 확인 필요 표시와 지난 대화 복원 | contract/web-attachments PR, 구현 agent #394·gateway #395 |
