"""감사 이벤트를 contracts/events/audit.schema.json 형식의 JSON Lines로 씁니다.

요청 원문, 위임 토큰 문자열, 모델이 쓴 자유 문장은 넣지 않습니다.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_runtime.registry import Requester
from agent_runtime.router import RouteDecision


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def write(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")


def route_decided(decision: RouteDecision, requester: Requester, via_delegation_token: bool = False) -> dict[str, Any]:
    return {
        "eventId": str(uuid.uuid4()),
        "occurredAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": "agent",
        "kind": "route.decided",
        "actor": {
            "employeeId": requester.employee_id,
            "viaDelegationToken": via_delegation_token,
            "agentId": decision.agent_id,
        },
        "conversationId": None,
        "routing": {
            "agentId": decision.agent_id,
            "method": decision.method,
            "reason": decision.audit_reason,
            "confidence": decision.confidence,
        },
        "result": "ok",
    }
