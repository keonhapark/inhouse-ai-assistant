"""업무 실행 시험 준비: 각본대로 답하는 LLM, 프로세스 안 MCP 도구 호출(가짜 erp), Runner 조립."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_runtime.audit import AuditLog
from agent_runtime.llm import LLMError
from agent_runtime.mcp_server.server import tool_descriptor
from agent_runtime.mcp_server.service import CallMeta
from agent_runtime.mcp_server.tokens import TokenVerifier
from agent_runtime.registry import Registry
from agent_runtime.run.graph import Deps, build_graph
from agent_runtime.run.policy import WideScope
from agent_runtime.run.runner import Runner
from agent_runtime.run.tools import ToolOutcome, ToolSpec, spec_from_mcp
from agent_runtime.run.trust import trusted_docs
from tests.conftest import PACK_DIR
from tests.mcp_support import KST, PUBLIC_KEY, Harness, make_harness

FIXED_NOW = datetime(2027, 3, 2, 10, 0, tzinfo=KST)  # 화요일


def call(name: str, args: dict[str, Any], cid: str = "") -> dict[str, Any]:
    return {"role": "assistant", "content": "",
            "tool_calls": [{"id": cid or f"c_{name}", "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]}


def say(text: str) -> dict[str, Any]:
    return {"role": "assistant", "content": text}


@dataclass
class ScriptedLLM:
    """chat()이 불릴 때마다 각본의 다음 답을 돌려줍니다. 받은 요청은 requests에 남깁니다."""

    script: list[Any] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)

    def chat(self, messages, tools=None, headers=None, model_policy=None):
        self.requests.append({"messages": json.loads(json.dumps(messages)), "tools": tools, "headers": headers,
                              "model_policy": model_policy})
        if not self.script:
            raise AssertionError("각본에 남은 LLM 답이 없습니다")
        nxt = self.script.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class InProcCaller:
    """MCP 서버의 ToolService를 프로세스 안에서 부릅니다(HTTP 대신). 호출을 calls에 남깁니다."""

    def __init__(self, h: Harness) -> None:
        self.h = h
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    async def list_tools(self, token: str) -> list[ToolSpec]:
        out = []
        for t in self.h.service.visible_tools(token):
            d = tool_descriptor(t)
            out.append(spec_from_mcp(d.name, d.description or "", d.input_schema, d.meta or {}))
        return out

    async def call(self, name: str, args: dict[str, Any], token: str, meta: dict[str, Any]) -> ToolOutcome:
        self.calls.append((name, args, meta))
        r = await self.h.service.call(name, args, token, CallMeta.from_meta(meta))
        return ToolOutcome(r.ok, r.payload)


@dataclass
class RunHarness:
    h: Harness
    llm: ScriptedLLM
    caller: InProcCaller
    runner: Runner
    audit_path: Path

    def agent_events(self) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        return [json.loads(x) for x in self.audit_path.read_text("utf-8").splitlines()]


def make_run_harness(tmp_path: Path, verify_tokens: bool = True, llm_error: bool = False) -> RunHarness:
    h = make_harness(tmp_path)
    llm = ScriptedLLM()
    caller = InProcCaller(h)
    audit_path = tmp_path / "agent-audit.jsonl"
    deps = Deps(llm=llm, caller=caller, audit=AuditLog(audit_path), wide=WideScope.from_pack(PACK_DIR),
                trusted_docs=trusted_docs(PACK_DIR), now=lambda: FIXED_NOW)
    registry = Registry.load(PACK_DIR)
    runner = Runner(registry, build_graph(deps), caller,
                    TokenVerifier.from_public_key(PUBLIC_KEY) if verify_tokens else None)
    return RunHarness(h, llm, caller, runner, audit_path)


__all__ = ["LLMError", "FIXED_NOW", "call", "say", "make_run_harness", "RunHarness", "ScriptedLLM"]
