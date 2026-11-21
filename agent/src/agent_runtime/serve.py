"""agent API와 MCP 서버를 한 프로세스에서 띄웁니다(compose: 8000 agent, 8001 MCP).

실행: uv run python -m agent_runtime.serve
환경 변수: AGENT_PORT(기본 8000), MCP_PORT(기본 8001), AGENT_HOST(기본 0.0.0.0)와
app.py·mcp_server/server.py의 변수(PACK_DIR, CONTRACTS_DIR, ERP_BASE_URL, RAG_BASE_URL, INCIDENT_BASE_URL,
DELEGATION_TOKEN_PUBLIC_KEY 또는 DELEGATION_JWKS_URL 등)
"""

from __future__ import annotations

import asyncio
import os

import uvicorn

from agent_runtime.app import create_app, services_from_env
from agent_runtime.mcp_server.server import create_mcp_app, service_from_env


async def main() -> None:
    host = os.environ.get("AGENT_HOST", "0.0.0.0")
    services = services_from_env()
    tool_service = service_from_env(services.registry, services.audit_log)
    servers = [
        uvicorn.Server(uvicorn.Config(create_app(services), host=host, port=int(os.environ.get("AGENT_PORT", "8000")))),
        uvicorn.Server(uvicorn.Config(create_mcp_app(tool_service, host=host), host=host,
                                      port=int(os.environ.get("MCP_PORT", "8001")))),
    ]
    await asyncio.gather(*(s.serve() for s in servers))


if __name__ == "__main__":
    asyncio.run(main())
