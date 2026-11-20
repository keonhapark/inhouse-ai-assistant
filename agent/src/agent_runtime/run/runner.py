"""/run·/resume 처리. 그래프 상태를 contracts/openapi/agent.yaml의 RunState로 바꿉니다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.types import Command

from agent_runtime.mcp_server.tokens import TokenError, TokenVerifier
from agent_runtime.registry import Agent, Registry, Requester
from agent_runtime.run.graph import TURN_RESET, RunContext, prepare_history
from agent_runtime.run.tools import ToolCaller


class Conflict(Exception):
    """기다리는 승인이 아니거나 이미 결정됨(409)."""


@dataclass
class Runner:
    registry: Registry
    graph: Any
    caller: ToolCaller
    verifier: TokenVerifier | None = None

    async def run(self, token: str, conversation_id: str, agent_id: str, message: str, requester: Requester,
                  condition: str = "full") -> dict[str, Any]:
        config = {"configurable": {"thread_id": conversation_id}}
        problem = self._check(token, conversation_id, agent_id, requester)
        if problem:
            return _blocked(conversation_id, agent_id, problem)
        snapshot = await self.graph.aget_state(config)
        if _waiting(snapshot):
            return self._view(conversation_id, agent_id, snapshot)
        agent = self.registry.get(agent_id)
        try:
            ctx = await self._context(token, agent, requester)
        except Exception as e:  # noqa: BLE001 - MCP 서버에 닿지 못하면 실패 상태로 돌려줍니다
            return _failed(conversation_id, agent_id, f"도구 목록을 가져오지 못했습니다({type(e).__name__})")
        prior = prepare_history((snapshot.values or {}).get("messages", []))
        state = {**TURN_RESET, "conversationId": conversation_id, "agentId": agent_id,
                 "requesterId": requester.employee_id, "condition": condition,
                 "messages": [*prior, {"role": "user", "content": message}]}
        try:
            await self.graph.ainvoke(state, config, context=ctx)
        except Exception as e:  # noqa: BLE001 - 그래프 오류는 failed 상태로 돌려줍니다
            return _failed(conversation_id, agent_id, f"실행 중 오류({type(e).__name__})")
        return self._view(conversation_id, agent_id, await self.graph.aget_state(config))

    async def resume(self, token: str, conversation_id: str, approval_id: str, decision: str,
                     requester_id: str | None = None) -> dict[str, Any]:
        config = {"configurable": {"thread_id": conversation_id}}
        snapshot = await self.graph.aget_state(config)
        values = snapshot.values or {}
        pending = values.get("pending") or {}
        if not _waiting(snapshot) or pending.get("approvalId") != approval_id:
            raise Conflict("기다리는 승인이 아닙니다")
        agent_id = values["agentId"]
        requester = Requester(values["requesterId"], "", "", ())
        problem = self._check(token, conversation_id, agent_id, requester, check_callable=False)
        if problem:
            return _blocked(conversation_id, agent_id, problem)
        agent = self.registry.get(agent_id)
        try:
            ctx = await self._context(token, agent, None)
        except Exception as e:  # noqa: BLE001
            return _failed(conversation_id, agent_id, f"도구 목록을 가져오지 못했습니다({type(e).__name__})")
        try:
            await self.graph.ainvoke(Command(resume={"decision": decision}), config, context=ctx)
        except Exception as e:  # noqa: BLE001
            return _failed(conversation_id, agent_id, f"실행 중 오류({type(e).__name__})")
        return self._view(conversation_id, agent_id, await self.graph.aget_state(config))

    def _check(self, token: str, conversation_id: str, agent_id: str, requester: Requester,
               check_callable: bool = True) -> str | None:
        if not self.registry.has(agent_id):
            return f"모르는 에이전트입니다: {agent_id}"
        if self.verifier is None:
            return None
        try:
            d = self.verifier.verify(token)
        except TokenError as e:
            return str(e)
        if d.agent_id != agent_id or d.employee_id != requester.employee_id or d.conversation_id != conversation_id:
            return "위임 토큰의 에이전트·요청자·대화가 요청과 다릅니다"
        return None

    async def _context(self, token: str, agent: Agent, requester: Requester | None) -> RunContext:
        # 요청자가 부를 수 없는 에이전트(fallback 포함)는 도구 없이 안내만 합니다.
        if requester is not None and not agent.callable_for(requester):
            return RunContext(token=token, agent=agent, tools=[])
        tools = [t for t in await self.caller.list_tools(token) if t.name in agent.tools]
        return RunContext(token=token, agent=agent, tools=tools)

    def _view(self, conversation_id: str, agent_id: str, snapshot: Any) -> dict[str, Any]:
        v = snapshot.values or {}
        state: dict[str, Any] = {
            "conversationId": conversation_id,
            "agentId": v.get("agentId", agent_id),
            "messages": [],
            "pendingApproval": None,
            "actions": v.get("actions", []),
            "citations": v.get("citations", []),
            "blockedReason": "; ".join(v.get("blocked", [])) or None,
        }
        if _waiting(snapshot):
            p = v["pending"]
            state["status"] = "awaiting_approval"
            state["messages"] = [{"role": "assistant", "content": "실행 전에 아래 내용을 확인해 주세요."}]
            state["pendingApproval"] = {"approvalId": p["approvalId"], "toolPreview": {
                "tool": p["tool"], "risk": p["risk"], "arguments": p["arguments"], "preview": p["preview"]}}
            return state
        state["status"] = v.get("status") or "completed"
        if v.get("final"):
            state["messages"] = [{"role": "assistant", "content": v["final"]}]
        return state


def _waiting(snapshot: Any) -> bool:
    return "approval" in (snapshot.next or ()) and bool((snapshot.values or {}).get("pending"))


def _blocked(conversation_id: str, agent_id: str, reason: str) -> dict[str, Any]:
    return {"conversationId": conversation_id, "agentId": agent_id, "status": "blocked",
            "messages": [{"role": "assistant", "content": f"요청을 처리할 수 없습니다: {reason}"}],
            "pendingApproval": None, "actions": [], "citations": [], "blockedReason": reason}


def _failed(conversation_id: str, agent_id: str, reason: str) -> dict[str, Any]:
    return {**_blocked(conversation_id, agent_id, reason), "status": "failed", "blockedReason": None,
            "messages": [{"role": "assistant", "content": f"지금은 처리하지 못했습니다: {reason}"}]}
