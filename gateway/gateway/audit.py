"""감사 이벤트(contracts/events/audit.schema.json)와 외부 전송 기록을 JSON Lines로 씁니다.

- audit.jsonl: 감사 이벤트. 토큰 문자열·가림 전 원문은 넣지 않습니다.
- egress.jsonl: 외부 모델로 나간 요청(가림 뒤)·가린 자리·응답. 가림 전 원문은 저장하지 않습니다. 커밋하지 않습니다.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


class JsonlWriter:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def write(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines() if x.strip()]


class AuditLog:
    def __init__(self, directory: Path):
        self.events = JsonlWriter(directory / "audit.jsonl")
        self.egress = JsonlWriter(directory / "egress.jsonl")

    def event(self, kind: str, *, employee_id: str | None, agent_id: str | None, via_token: bool,
              result: str, conversation_id: str | None = None, model: dict[str, Any] | None = None,
              problem_type: str | None = None, detail: str | None = None,
              delegation_token_id: str | None = None, routing: dict[str, Any] | None = None,
              channel: str | None = None) -> str:
        """channel은 요청이 들어온 입구(web·slack·agent, 계약 #339). 모르면 None이고 actor에 넣지 않습니다."""
        event_id = "evt_" + uuid.uuid4().hex
        self.events.write({
            "eventId": event_id,
            "occurredAt": now_iso(),
            "source": "gateway",
            "kind": kind,
            "actor": {"employeeId": employee_id, "viaDelegationToken": via_token, "agentId": agent_id,
                      "delegationTokenId": delegation_token_id, **({"channel": channel} if channel else {})},
            "conversationId": conversation_id,
            "model": model,
            "result": result,
            "problemType": problem_type,
            "detail": detail,
            **({"routing": routing} if routing is not None else {}),
        })
        return event_id
