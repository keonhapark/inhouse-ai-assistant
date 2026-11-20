"""MCP 프로토콜로 부릅니다: 프로세스 안 연결과, 실제 Streamable HTTP(헤더로 위임 토큰)."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from agent_runtime.mcp_server.server import build_server, create_mcp_app
from tests.mcp_support import Harness, make_harness, mint


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def h(tmp_path: Path) -> Harness:
    return make_harness(tmp_path)


@pytest.mark.anyio
async def test_inproc_list_and_call_without_token(h: Harness) -> None:
    async with Client(build_server(h.service)) as client:
        listed = await client.list_tools()
        names = {t.name for t in listed.tools}
        assert names == {t.name for t in h.service.catalog.tools}
        result = await client.call_tool("leave_get_balance", {})
        assert result.is_error
        assert result.structured_content["problem"]["type"] == "urn:problem:unauthorized"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def http_server(h: Harness) -> Iterator[str]:
    port = _free_port()
    config = uvicorn.Config(create_mcp_app(h.service, host="127.0.0.1"), host="127.0.0.1", port=port,
                            log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{base}/health").status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    yield base
    server.should_exit = True
    thread.join(timeout=5)


@pytest.mark.anyio
async def test_http_token_header_filters_and_authorizes(h: Harness, http_server: str) -> None:
    token = mint(agent="assistant")
    async with httpx2.AsyncClient(headers={"X-Delegation-Token": token}, timeout=30) as http:
        async with Client(streamable_http_client(f"{http_server}/mcp", http_client=http)) as client:
            listed = await client.list_tools()
            assert {t.name for t in listed.tools} == set(h.service.registry.get("assistant").tools)
            room = next(t for t in listed.tools if t.name == "room_reserve")
            assert room.meta["risk"] == "reversible_write"
            assert room.meta["trustRequired"] == "user_direct"

            ok = await client.call_tool("room_list_my_reservations", {})
            assert not ok.is_error, ok.structured_content
            assert "items" in ok.structured_content

            denied = await client.call_tool("leave_get_balance", {})
            assert denied.structured_content["problem"]["type"] == "urn:problem:tool-not-allowed"

            preview = await client.call_tool(
                "room_cancel_reservation", {"reservationId": "missing"},
                meta={"trustLevel": "user_direct", "dryRun": True},
            )
            assert preview.structured_content["problem"]["type"] == "urn:problem:not-found"
    assert token not in h.audit_path.read_text("utf-8")


def test_health(h: Harness, http_server: str) -> None:
    assert httpx.get(f"{http_server}/health").json() == {"status": "ok"}
    assert json.loads(httpx.get(f"{http_server}/health").text)["status"] == "ok"
