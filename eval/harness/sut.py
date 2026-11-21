"""평가 대상 시스템과 대화하는 경계.

실제 실행은 gateway 계약(contracts/openapi/gateway.yaml)의 사람 화면 경로로 대화합니다.
시험에서는 같은 Protocol을 따르는 스텁을 씁니다.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
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
    # 외부 요청 기록의 model(LiteLLM에 넘긴 모델 이름)
    external_models: list[str] = field(default_factory=list)


class ChatSystem(Protocol):
    def start(self, requester: str) -> str: ...

    def send(self, conversation_id: str, text: str,
             attachments: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]: ...

    def decide(self, conversation_id: str, approval_id: str, decision: str) -> list[dict[str, Any]]: ...

    def collect(self, conversation_id: str) -> Collected: ...


def count_orphan_external(external_log: ExternalLog | None, since: datetime, until: datetime) -> int | None:
    """since~until 사이에 대화 ID(conversationId) 없이 외부로 나간 요청 수. 어느 회차에도 붙지 않아 판정에서
    빠지므로 보고서에 경고로 셉니다(#294). 외부 요청 기록을 읽지 못하면 None."""
    if external_log is None:
        return None
    records = external_log(None)
    if records is None:
        return None
    n = 0
    for r in records:
        try:
            at = datetime.fromisoformat(str(r.get("at", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if since <= at <= until:
            n += 1
    return n


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


# 외부 요청 기록 수집기: 대화 ID → 외부 요청 기록 목록(contracts/events/external-request.schema.json 한 줄씩).
# 수집할 수 없으면 None
ExternalLog = Callable[[str | None], list[dict[str, Any]] | None]


def jsonl_external_log(path: Path) -> ExternalLog:
    """gateway가 GATEWAY_EXTERNAL_LOG에 쓰는 JSON Lines(contracts/events/external-request.schema.json)에서
    대화 ID가 같은 줄의 body를 읽습니다. 파일이 없으면 외부로 보낸 요청이 없는 것으로 봅니다(빈 목록).
    gateway에 같은 경로를 설정했는지는 실행하는 쪽이 맞춥니다."""

    def read(conversation_id: str) -> list[Any]:
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("conversationId") == conversation_id:
                out.append(rec)
        return out

    return read


def docker_external_log(container: str, path: str) -> ExternalLog:
    """외부 요청 기록이 컨테이너 볼륨 안에만 있을 때(compose의 /audit) docker exec로 읽습니다.
    파일이 없으면 외부로 보낸 요청이 없는 것으로 봅니다(빈 목록). docker를 부르지 못하면 None(수집 못 함)."""
    import subprocess

    def read(conversation_id: str) -> list[Any] | None:
        try:
            r = subprocess.run(["docker", "exec", container, "sh", "-c", f"cat {path} 2>/dev/null || true"],
                               capture_output=True, text=True, timeout=30, check=True)
        except (OSError, subprocess.SubprocessError):
            return None
        out = []
        for line in r.stdout.splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("conversationId") == conversation_id:
                    out.append(rec)
        return out

    return read


class GatewayChat:
    """gateway에 직원으로 로그인해 대화합니다. 감사 이벤트는 감사 역할 직원으로 읽습니다."""

    def __init__(self, client: httpx.Client, *, auditor: str | None, password: str | None = None,
                 external_log: ExternalLog | None = None, condition: str | None = None) -> None:
        self.c = client
        # 평가 조건. gateway가 GATEWAY_EVAL_MODE=1일 때만 X-Eval-Condition 헤더를 받습니다
        self.condition = condition
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
        headers = self._headers(requester)
        if self.condition:
            headers["X-Eval-Condition"] = self.condition
        r = self.c.post("/conversations", json={}, headers=headers)
        r.raise_for_status()
        cid = r.json()["conversationId"]
        self._owner[cid] = requester
        return cid

    def send(self, conversation_id: str, text: str,
             attachments: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"content": text}
        if attachments:
            body["attachments"] = attachments
        return self._stream(self._owner[conversation_id], f"/conversations/{conversation_id}/messages", body)

    def decide(self, conversation_id: str, approval_id: str, decision: str) -> list[dict[str, Any]]:
        return self._stream(self._owner[conversation_id], f"/execution-approvals/{approval_id}",
                            {"decision": decision})

    def orphan_external(self, since: datetime, until: datetime) -> int | None:
        """회차 시간 동안 대화 ID 없이 나간 외부 요청 수(#294)."""
        return count_orphan_external(self.external_log, since, until)

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
            records = self.external_log(conversation_id)
            if records is not None:
                out.external_requests = [r["body"] for r in records]
                out.external_models = [r["model"] for r in records if r.get("model")]
                out.cost_usd = external_cost(records)
        return out


def external_cost(records: list[dict[str, Any]]) -> float | None:
    """외부 요청 기록의 costUsd 합. 로컬 호출은 기록되지 않으므로 외부 요청이 없으면 0입니다.
    비용을 모르는(null) 요청이 하나라도 있으면 None입니다."""
    costs = [r.get("costUsd") for r in records]
    if any(c is None for c in costs):
        return None
    return float(sum(costs))
