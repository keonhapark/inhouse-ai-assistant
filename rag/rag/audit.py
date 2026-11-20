"""감사 이벤트(contracts/events/audit.schema.json)를 JSON Lines로 씁니다.

위임 토큰 문자열과 질문 원문은 넣지 않습니다. 질문에 개인정보가 들어 있을 수 있기 때문입니다.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class AuditLog:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def write(
        self,
        kind: str,
        result: str,
        claims: dict[str, Any] | None,
        operation: str,
        *,
        model: dict[str, Any] | None = None,
        problem: str | None = None,
        detail: str | None = None,
    ) -> dict[str, Any]:
        event = {
            "eventId": uuid.uuid4().hex,
            "occurredAt": now_iso(),
            "source": "rag",
            "kind": kind,
            "actor": {
                "employeeId": claims.get("sub") if claims else None,
                "viaDelegationToken": claims is not None,
                "agentId": claims.get("agt") if claims else None,
            },
            "conversationId": claims.get("cid") if claims else None,
            "operation": operation,
            "model": model,
            "result": result,
            "problemType": f"urn:problem:{problem}" if problem else None,
            "detail": detail,
        }
        line = json.dumps(event, ensure_ascii=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        return event
