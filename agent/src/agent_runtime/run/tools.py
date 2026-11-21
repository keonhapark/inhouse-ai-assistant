"""업무 실행이 도구를 부르는 길. 기본은 MCP 서버(Streamable HTTP)이고 위임 토큰은 요청 헤더로만 넘깁니다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from agent_runtime.run.policy import ToolMeta


@dataclass(frozen=True)
class ToolSpec:
    meta: ToolMeta
    description: str
    input_schema: dict[str, Any]
    service: str  # 출력 신뢰 판단용(erp, rag, incident)

    @property
    def name(self) -> str:
        return self.meta.name


@dataclass(frozen=True)
class ToolOutcome:
    ok: bool
    payload: dict[str, Any]


class ToolCaller(Protocol):
    async def list_tools(self, token: str) -> list[ToolSpec]: ...

    async def call(self, name: str, args: dict[str, Any], token: str, meta: dict[str, Any]) -> ToolOutcome: ...


class McpToolCaller:
    """MCP 서버에 붙어 도구를 부릅니다. 호출 하나마다 연결을 엽니다(1단계는 단순함을 택함)."""

    TOKEN_HEADER = "X-Delegation-Token"

    def __init__(self, url: str, timeout_s: float = 120) -> None:
        self.url = url
        self.timeout_s = timeout_s

    def _client(self, token: str) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(headers={self.TOKEN_HEADER: token}, timeout=self.timeout_s)

    async def list_tools(self, token: str) -> list[ToolSpec]:
        async with self._client(token) as http, Client(streamable_http_client(self.url, http_client=http)) as c:
            listed = await c.list_tools()
        return [spec_from_mcp(t.name, t.description or "", t.input_schema, t.meta or {}) for t in listed.tools]

    async def call(self, name: str, args: dict[str, Any], token: str, meta: dict[str, Any]) -> ToolOutcome:
        async with self._client(token) as http, Client(streamable_http_client(self.url, http_client=http)) as c:
            r = await c.call_tool(name, args, meta=meta)
        payload = r.structured_content
        if payload is None:
            text = next((x.text for x in r.content if getattr(x, "type", "") == "text"), "{}")
            payload = json.loads(text)
        return ToolOutcome(not r.is_error, payload)


def spec_from_mcp(name: str, description: str, input_schema: dict[str, Any], meta: dict[str, Any]) -> ToolSpec:
    return ToolSpec(
        meta=ToolMeta(name, meta.get("risk", "irreversible"), meta.get("trustRequired", "user_direct")),
        description=description,
        input_schema=dict(input_schema),
        service=meta.get("service") if meta.get("service") in ("rag", "incident") else "erp",
    )


def openai_tool(spec: ToolSpec) -> dict[str, Any]:
    return {"type": "function",
            "function": {"name": spec.name, "description": spec.description, "parameters": spec.input_schema}}
