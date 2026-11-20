"""평가 대상 시스템과 대화하는 경계.

실제 실행은 gateway 계약(contracts/openapi/gateway.yaml)의 사람 화면 경로로 대화합니다.
시험에서는 같은 Protocol을 따르는 스텁을 씁니다.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass
class Collected:
    """대화가 끝난 뒤 모으는 기록."""

    audit_events: list[dict[str, Any]] = field(default_factory=list)
    external_requests: list[Any] | None = None
    logs: list[str] = field(default_factory=list)
    # 이 대화의 LLM 비용(달러). 대상 시스템이 알려 주지 않으면 None
    cost_usd: float | None = None


class ChatSystem(Protocol):
    def start(self, requester: str) -> str: ...

    def send(self, conversation_id: str, text: str) -> list[dict[str, Any]]: ...

    def decide(self, conversation_id: str, approval_id: str, decision: str) -> list[dict[str, Any]]: ...

    def collect(self, conversation_id: str) -> Collected: ...


def parse_sse(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    """text/event-stream을 ChatEvent로 풉니다. data 줄이 여러 개면 줄바꿈으로 잇습니다."""
    data: list[str] = []
    for line in lines:
        line = line.rstrip("\r")
        if line == "":
            if data:
                yield json.loads("\n".join(data))
                data = []
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        if name == "data":
            data.append(value[1:] if value.startswith(" ") else value)
    if data:
        yield json.loads("\n".join(data))


# 외부 요청 기록 수집기: 대화 ID → 외부 요청 본문 목록. 수집할 수 없으면 None
ExternalLog = Callable[[str], list[Any] | None]


class GatewayChat:
    """gateway에 직원으로 로그인해 대화합니다. 감사 이벤트는 감사 역할 직원으로 읽습니다."""

    def __init__(self, client: httpx.Client, *, auditor: str | None, password: str | None = None,
                 external_log: ExternalLog | None = None) -> None:
        self.c = client
        self.auditor = auditor
        self.password = password or os.environ.get("ERP_DEMO_PASSWORD", "demo")
        self.external_log = external_log
        self._tokens: dict[str, str] = {}
        self._owner: dict[str, str] = {}

    def _token(self, employee: str) -> str:
        if employee not in self._tokens:
            r = self.c.post("/auth/login", json={"employeeNo": employee, "password": self.password})
            r.raise_for_status()
            self._tokens[employee] = r.json()["accessToken"]
        return self._tokens[employee]

    def _headers(self, employee: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token(employee)}"}

    def _stream(self, employee: str, path: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        headers = {**self._headers(employee), "Accept": "text/event-stream"}
        with self.c.stream("POST", path, json=body, headers=headers) as r:
            if r.status_code != 200:
                r.read()
                raise httpx.HTTPStatusError(f"{path}: {r.status_code} {r.text[:300]}", request=r.request,
                                            response=r)
            return list(parse_sse(r.iter_lines()))

    def start(self, requester: str) -> str:
        r = self.c.post("/conversations", json={}, headers=self._headers(requester))
        r.raise_for_status()
        cid = r.json()["conversationId"]
        self._owner[cid] = requester
        return cid

    def send(self, conversation_id: str, text: str) -> list[dict[str, Any]]:
        return self._stream(self._owner[conversation_id], f"/conversations/{conversation_id}/messages",
                            {"content": text})

    def decide(self, conversation_id: str, approval_id: str, decision: str) -> list[dict[str, Any]]:
        return self._stream(self._owner[conversation_id], f"/execution-approvals/{approval_id}",
                            {"decision": decision})

    def collect(self, conversation_id: str) -> Collected:
        out = Collected()
        if self.auditor:
            cursor = None
            while True:
                params: dict[str, Any] = {"conversationId": conversation_id, "limit": 500}
                if cursor:
                    params["cursor"] = cursor
                r = self.c.get("/audit-events", params=params, headers=self._headers(self.auditor))
                r.raise_for_status()
                page = r.json()
                out.audit_events.extend(page["items"])
                cursor = page.get("nextCursor")
                if not cursor:
                    break
        if self.external_log:
            out.external_requests = self.external_log(conversation_id)
        return out
