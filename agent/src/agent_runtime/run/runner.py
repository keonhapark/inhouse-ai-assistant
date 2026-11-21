"""/run·/resume 처리. 그래프 상태를 contracts/openapi/agent.yaml의 RunState로 바꿉니다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.types import Command

from agent_runtime.mcp_server.tokens import TokenError, TokenVerifier
from agent_runtime.registry import Agent, Registry, Requester
from agent_runtime.run.graph import TURN_RESET, UNTRUSTED_NOTE, RunContext, prepare_history
from agent_runtime.run.image_reading import ImageReader, ImageSpec, attachment_note
from agent_runtime.run.tools import ToolCaller


class Conflict(Exception):
    """기다리는 승인이 아니거나 이미 결정됨(409)."""


@dataclass
class Runner:
    registry: Registry
    graph: Any
    caller: ToolCaller
    verifier: TokenVerifier | None = None
    images: ImageReader | None = None

    async def run(self, token: str, conversation_id: str, agent_id: str, message: str, requester: Requester,
                  condition: str = "full", attachments: list[str] | None = None,
                  route_method: str | None = None) -> dict[str, Any]:
        config = {"configurable": {"thread_id": conversation_id}}
        problem, token_id = self._check(token, conversation_id, agent_id, requester)
        if problem:
            return _blocked(conversation_id, agent_id, problem)
        snapshot = await self.graph.aget_state(config)
        if _waiting(snapshot):
            return self._view(conversation_id, agent_id, snapshot)
        agent = self.registry.get(agent_id)
        try:
            ctx = await self._context(token, agent, requester, token_id)
        except Exception as e:  # noqa: BLE001 - MCP 서버에 닿지 못하면 실패 상태로 돌려줍니다
            return _failed(conversation_id, agent_id, f"도구 목록을 가져오지 못했습니다({type(e).__name__})")
        prior = prepare_history((snapshot.values or {}).get("messages", []))
        state = {**TURN_RESET, "conversationId": conversation_id, "agentId": agent_id,
                 "requesterId": requester.employee_id, "condition": condition}
        if route_method == "fallback":
            # 부서를 고르지 못한 대화는 끝까지 로컬로 실행합니다(#308). 뒤 턴에서 routeMethod가 없어도 풀리지 않습니다.
            state["force_local"] = True
        turn = [{"role": "user", "content": message}]
        if attachments:
            note, tainted, draft_tool = await self._read_attachments(attachments, token, agent, requester, ctx)
            # 사용자 발화와 섞지 않고 따로 둡니다.
            turn.append({"role": "user", "content": note})
            if tainted:
                # 이미지 글자는 신뢰할 수 없는 내용입니다(결정 0004 덧붙임). 같은 턴에는 팩 image_reading.draft_tool만
                # 막지 않고 미리보기 승인으로 보내고, 다른 user_direct 도구는 막습니다. 다음 턴부터는 모두 승인을 받습니다.
                state["tainted"] = True
                state["taint_exempt"] = [draft_tool] if draft_tool else []
                state["conversation_tainted"] = True
                # 이미지에서 읽은 글자가 대화에 실렸으므로 에이전트 정책과 관계없이 끝까지 로컬로 실행합니다
                # (#413, 기획서 우려 19 "OCR 텍스트를 외부로 보내는 것은 기본 꺼 둠", #308과 같은 장치).
                state["force_local"] = True
        state["messages"] = [*prior, *turn]
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
        problem, token_id = self._check(token, conversation_id, agent_id, requester, check_callable=False)
        if problem:
            return _blocked(conversation_id, agent_id, problem)
        agent = self.registry.get(agent_id)
        try:
            ctx = await self._context(token, agent, None, token_id)
        except Exception as e:  # noqa: BLE001
            return _failed(conversation_id, agent_id, f"도구 목록을 가져오지 못했습니다({type(e).__name__})")
        try:
            await self.graph.ainvoke(Command(resume={"decision": decision}), config, context=ctx)
        except Exception as e:  # noqa: BLE001
            return _failed(conversation_id, agent_id, f"실행 중 오류({type(e).__name__})")
        return self._view(conversation_id, agent_id, await self.graph.aget_state(config))

    async def _read_attachments(self, data_urls: list[str], token: str, agent: Agent, requester: Requester,
                                ctx: RunContext) -> tuple[str, bool, str | None]:
        """(사용자 발화 뒤에 둘 글, 읽은 값이 있는지, 같은 턴 예외 도구). 이미지 본문은 상태에 넣지 않습니다.

        팩에 image_reading이 없는 에이전트, 요청자가 부를 수 없어 도구가 없는 대화는 읽지 않습니다.
        """
        spec = ImageSpec.from_agent(agent)
        if self.images is None or spec is None or not agent.callable_for(requester):
            return f"[첨부 이미지 {len(data_urls)}장은 이 에이전트에서 읽지 않았습니다]", False, None
        results = await self.images.read_all(data_urls, token, spec)
        draft = spec.draft_tool if spec.draft_tool and ctx.spec(spec.draft_tool) else None
        return attachment_note(results, spec, UNTRUSTED_NOTE), any(r is not None for r in results), draft

    def _check(self, token: str, conversation_id: str, agent_id: str, requester: Requester,
               check_callable: bool = True) -> tuple[str | None, str | None]:
        """(막는 이유, 위임 토큰 jti)를 돌려줍니다."""
        if not self.registry.has(agent_id):
            return f"모르는 에이전트입니다: {agent_id}", None
        if self.verifier is None:
            return None, None
        try:
            d = self.verifier.verify(token)
        except TokenError as e:
            return str(e), None
        if d.agent_id != agent_id or d.employee_id != requester.employee_id or d.conversation_id != conversation_id:
            return "위임 토큰의 에이전트·요청자·대화가 요청과 다릅니다", None
        return None, d.jti

    async def _context(self, token: str, agent: Agent, requester: Requester | None,
                       token_id: str | None = None) -> RunContext:
        # 요청자가 부를 수 없는 에이전트(fallback 포함)는 도구 없이 안내만 합니다.
        if requester is not None and not agent.callable_for(requester):
            return RunContext(token=token, agent=agent, tools=[], token_id=token_id)
        tools = [t for t in await self.caller.list_tools(token) if t.name in agent.tools]
        return RunContext(token=token, agent=agent, tools=tools, token_id=token_id)

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
