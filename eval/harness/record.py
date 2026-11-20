"""시나리오 한 회차의 실행 기록. 판정기는 이것만 봅니다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Clarification:
    question: str
    answer: str
    matched: bool


@dataclass
class RunRecord:
    scenario_id: str
    conversation_id: str | None = None
    # gateway ChatEvent(contracts/openapi/gateway.yaml) 순서대로
    events: list[dict[str, Any]] = field(default_factory=list)
    # 외부 LLM 요청 본문. None이면 수집하지 못한 것(빈 목록과 구분)
    external_requests: list[Any] | None = None
    # 외부 요청 기록에 적힌 모델 이름
    external_models: list[str] = field(default_factory=list)
    # 감사 이벤트(contracts/events/audit.schema.json)
    audit_events: list[dict[str, Any]] = field(default_factory=list)
    # 그 밖의 로그 줄
    logs: list[str] = field(default_factory=list)
    clarifications: list[Clarification] = field(default_factory=list)
    # 하네스 쪽 오류(시간 초과, 연결 실패 등). 있으면 "실패로 끝남"
    error: str | None = None
    # 실행 환경 문제로 보이는 이유(gateway 연결 실패 등). 있으면 이어 돌릴 때 다시 돌릴 후보
    env_failure: str | None = None
    # 대상 시스템이 재시도 가능하다고 표시한 오류 이벤트가 있었음. 실행 환경 문제인지는 실행기가 모델 서버를 확인해 정합니다
    retryable_event: bool = False
    timed_out: bool = False
    cost_usd: float | None = None
    duration_s: float | None = None
