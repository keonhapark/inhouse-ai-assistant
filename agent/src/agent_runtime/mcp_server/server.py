"""MCP 서버(Streamable HTTP, /mcp). 위임 토큰은 HTTP 요청 헤더 X-Delegation-Token으로만 받습니다.

도구 메타데이터
- annotations: readOnlyHint(risk=read), destructiveHint(risk=irreversible)
- _meta: risk, trustRequired, requiredScope, stage

도구 호출 _meta(선택): dryRun(bool), idempotencyKey(str), trustLevel(trusted|untrusted|user_direct)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import anyio
import httpx
import mcp_types as types
from mcp.server.lowlevel import Server
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agent_runtime.audit import AuditLog
from agent_runtime.mcp_server.catalog import Catalog, Tool
from agent_runtime.mcp_server.service import CallMeta, ToolService
from agent_runtime.mcp_server.tokens import TokenVerifier
from agent_runtime.registry import Registry

TOKEN_HEADER = "x-delegation-token"


def tool_descriptor(tool: Tool) -> types.Tool:
    return types.Tool(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_schema,
        annotations=types.ToolAnnotations(
            read_only_hint=tool.risk == "read",
            destructive_hint=tool.risk == "irreversible",
            open_world_hint=False,
        ),
        meta={
            "risk": tool.risk,
            "trustRequired": tool.trust_required,
            "requiredScope": tool.required_scope,
            "stage": tool.stage,
        },
    )


def _token(ctx: Any) -> str | None:
    request = getattr(ctx, "request", None)
    headers = getattr(request, "headers", None)
    return headers.get(TOKEN_HEADER) if headers is not None else None


def build_server(service: ToolService) -> Server:
    async def on_list_tools(ctx: Any, params: types.PaginatedRequestParams | None) -> types.ListToolsResult:
        visible = await anyio.to_thread.run_sync(service.visible_tools, _token(ctx))
        return types.ListToolsResult(tools=[tool_descriptor(t) for t in visible])

    async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        meta = CallMeta.from_meta(dict(params.meta) if params.meta else None)
        result = await service.call(params.name, params.arguments, _token(ctx), meta)
        payload = result.payload
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
            structured_content=payload,
            is_error=not result.ok,
        )

    return Server("agent-mcp", version="0.1.0", on_list_tools=on_list_tools, on_call_tool=on_call_tool)


def service_from_env(registry: Registry, audit_log: AuditLog) -> ToolService:
    contracts = Path(os.environ.get("CONTRACTS_DIR", "../contracts"))
    catalog = Catalog.load(contracts / "mcp" / "tools.json", contracts / "openapi", registry)
    erp = os.environ.get("ERP_BASE_URL", "http://localhost:8040/api/v1")
    rag = os.environ.get("RAG_BASE_URL", "http://localhost:8030")
    backends = {
        # 계약 경로에 /api/v1이 들어 있으므로 erp는 호스트까지만 씁니다.
        "erp": httpx.AsyncClient(base_url=_origin(erp), timeout=30),
        "rag": httpx.AsyncClient(base_url=rag.rstrip("/"), timeout=120),
    }
    return ToolService(catalog, registry, TokenVerifier.from_env(), backends, audit_log)


def _origin(url: str) -> str:
    scheme, rest = url.split("://", 1)
    return f"{scheme}://{rest.split('/', 1)[0]}"


def create_mcp_app(service: ToolService, host: str = "0.0.0.0") -> Starlette:
    server = build_server(service)

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    # host가 0.0.0.0이면 SDK의 localhost DNS 리바인딩 보호가 켜지지 않습니다(컨테이너끼리 서비스 이름으로 부름).
    return server.streamable_http_app(
        streamable_http_path="/mcp",
        host=host,
        custom_starlette_routes=[Route("/health", health)],
    )
