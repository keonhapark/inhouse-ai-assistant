"""채팅 화면 API: 에이전트 목록, 대화, 메시지 SSE, 실행 승인(contracts/openapi/gateway.yaml).

흐름(메시지 하나)
1. 대화에 에이전트가 없으면 agent `/route`로 한 번만 고릅니다(직원이 골랐으면 explicit). → `route` 이벤트
2. 요청자가 그 에이전트를 부를 수 있는지(callable_by) 보고, 대화용 위임 토큰(10분)을 새로 발급합니다.
3. agent `/run`에 토큰을 `X-Delegation-Token` 헤더로만 넘기고, 돌아온 RunState를 ChatEvent로 바꿔 흘려보냅니다.
4. 실행 승인이 필요하면 `approval_required`를 보내고 대화를 `awaiting_approval`로 둡니다. 그동안 새 메시지는 409입니다.
5. `POST /execution-approvals/{id}`는 요청자 본인만 결정하고, agent `/resume`의 결과를 같은 방식으로 흘려보냅니다.
마지막 이벤트는 항상 `done`입니다. agent가 답하지 않으면 `error`(retryable)를 보내고 대화는 그대로 둡니다.

대화와 승인은 프로세스 메모리에 둡니다(1단계). gateway를 다시 띄우면 사라지고, LangGraph 상태는 agent 쪽에 남습니다.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from gateway.audit import AuditLog
from gateway.delegation import DelegationService, load_requester
from gateway.erp_client import ErpClient
from gateway.problems import ProblemError
from gateway.registry import Registry, Requester, grant_matches
from gateway.relay import bearer

APPROVAL_TTL = timedelta(minutes=10)
MAX_CONTENT = 4000


def now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds")


class AgentUnavailable(Exception):
    pass


class AgentClient:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 120.0):
        self._http = httpx.AsyncClient(base_url=base_url, transport=transport,
                                       timeout=httpx.Timeout(timeout, connect=5.0))

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post(self, path: str, body: dict[str, Any], token: str | None = None) -> httpx.Response:
        headers = {"X-Delegation-Token": token} if token else {}
        try:
            return await self._http.post(path, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise AgentUnavailable(type(e).__name__) from e

    async def route(self, message: str, requester: dict[str, Any]) -> dict[str, Any]:
        r = await self._post("/route", {"message": message, "requester": requester})
        if r.status_code != 200:
            raise AgentUnavailable(f"route {r.status_code}")
        return r.json()

    async def run(self, token: str, body: dict[str, Any]) -> dict[str, Any]:
        r = await self._post("/run", body, token)
        if r.status_code != 200:
            raise AgentUnavailable(f"run {r.status_code}")
        return r.json()

    async def resume(self, token: str, body: dict[str, Any]) -> httpx.Response:
        return await self._post("/resume", body, token)


@dataclass
class Approval:
    id: str
    conversation_id: str
    owner: str
    tool: str
    expires_at: datetime
    decided: str | None = None


@dataclass
class Conversation:
    id: str
    owner: str
    created_at: datetime
    agent_id: str | None = None
    routed: bool = False
    title: str | None = None
    status: str = "active"
    updated_at: datetime | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    seq: int = 0
    pending: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def event(self, type_: str, **fields: Any) -> dict[str, Any]:
        t = now()
        ev = {"type": type_, "conversationId": self.id, "seq": self.seq, "at": iso(t), **fields}
        self.seq += 1
        self.events.append(ev)
        self.updated_at = t
        return ev


def sse(ev: dict[str, Any]) -> bytes:
    return f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n".encode()


def agent_requester(who: Requester) -> dict[str, Any]:
    return {"employeeId": who.id, "unitId": who.unit_id, "grade": who.grade, "roles": list(who.roles)}


class ChatService:
    def __init__(self, erp: ErpClient, registry: Registry, delegation: DelegationService, agent: AgentClient,
                 audit: AuditLog):
        self.erp, self.registry, self.delegation, self.agent, self.audit = erp, registry, delegation, agent, audit
        self.conversations: dict[str, Conversation] = {}
        self.approvals: dict[str, Approval] = {}

    # ---------- 조회 ----------
    def summary(self, c: Conversation) -> dict[str, Any]:
        agent = self.registry.get(c.agent_id) if c.agent_id else None
        return {"conversationId": c.id, "agentId": c.agent_id, "agentName": agent.name if agent else None,
                "title": c.title, "status": c.status, "createdAt": iso(c.created_at),
                "updatedAt": iso(c.updated_at or c.created_at)}

    def owned(self, conversation_id: str, who: Requester) -> Conversation:
        c = self.conversations.get(conversation_id)
        if c is None or c.owner != who.id:
            raise ProblemError(404, "not-found", "대화가 없습니다")
        return c

    # ---------- 이벤트 만들기 ----------
    def _token(self, who: Requester, c: Conversation) -> str:
        issued = self.delegation.issue_for(who, c.agent_id, c.id)
        self.audit.event("auth.delegation_token_issued", employee_id=who.id, agent_id=c.agent_id, via_token=False,
                         result="ok", conversation_id=c.id, detail=f"jti={issued.claims['jti']}")
        return issued.token

    def _state_events(self, c: Conversation, who: Requester, state: dict[str, Any]) -> list[dict[str, Any]]:
        out = []
        for a in state.get("actions") or []:
            out.append(c.event("action", action={k: a[k] for k in ("actionId", "tool", "summary", "undoable")}))
        for m in state.get("messages") or []:
            out.append(c.event("message", text=m["content"]))
        if state.get("citations"):
            out.append(c.event("citations", citations=state["citations"]))
        status = state.get("status")
        pending = state.get("pendingApproval")
        if status == "awaiting_approval" and pending:
            tp = pending["toolPreview"]
            ap = Approval(pending["approvalId"], c.id, who.id, tp["tool"], now() + APPROVAL_TTL)
            self.approvals[ap.id] = ap
            c.status, c.pending = "awaiting_approval", ap.id
            out.append(c.event("approval_required", approval={
                "approvalId": ap.id, "tool": tp["tool"], "risk": tp["risk"], "preview": tp["preview"],
                "expiresAt": iso(ap.expires_at)}))
            self.audit.event("execution_approval.requested", employee_id=who.id, agent_id=c.agent_id,
                             via_token=False, result="pending", conversation_id=c.id, detail=f"approval={ap.id}")
        else:
            c.status, c.pending = "active", None
        if status == "blocked":
            out.append(c.event("blocked", blocked={"reason": state.get("blockedReason") or "장치가 막았습니다",
                                                   "code": "policy_denied"}))
        elif status == "failed":
            out.append(c.event("error", error={"message": "에이전트 실행이 실패했습니다", "retryable": False}))
        return out

    def _agent_down(self, c: Conversation) -> dict[str, Any]:
        return c.event("error", error={"message": "에이전트가 답하지 않았습니다. 잠시 뒤 다시 보내 주세요",
                                       "retryable": True})

    # ---------- 메시지 ----------
    async def message_events(self, c: Conversation, who: Requester, content: str) -> AsyncIterator[dict[str, Any]]:
        async with c.lock:
            if c.status == "awaiting_approval":  # 앞 메시지가 승인 대기로 끝났으면 이 메시지는 받지 않습니다
                yield c.event("error", error={"message": "실행 승인을 기다리는 중입니다", "retryable": False})
                yield c.event("done")
                return
            c.events.append({"type": "user_message", "content": content, "at": iso(now())})
            c.title = c.title or content[:40]
            if not c.routed:
                if c.agent_id is None:
                    try:
                        d = await self.agent.route(content, agent_requester(who))
                    except AgentUnavailable:
                        yield self._agent_down(c)
                        yield c.event("done")
                        return
                    agent = self.registry.get(d.get("agentId", ""))
                    if agent is None:
                        yield c.event("error", error={"message": "등록부에 없는 에이전트로 라우팅됐습니다",
                                                      "retryable": False})
                        yield c.event("done")
                        return
                    route = {"agentId": agent.id, "agentName": agent.name, "method": d.get("method", "llm"),
                             "reason": d.get("reason", ""), "suggestedAgentId": d.get("suggestedAgentId")}
                else:
                    agent = self.registry.get(c.agent_id)
                    route = {"agentId": agent.id, "agentName": agent.name, "method": "explicit",
                             "reason": "직원이 골랐습니다", "suggestedAgentId": None}
                if not grant_matches(agent.callable_by, who):
                    yield c.event("blocked", blocked={"reason": f"{agent.name} 에이전트를 부를 수 없습니다",
                                                      "code": "agent_not_callable"})
                    yield c.event("done")
                    return
                c.agent_id, c.routed = agent.id, True
                yield c.event("route", route=route)

            token = self._token(who, c)
            try:
                state = await self.agent.run(token, {"conversationId": c.id, "agentId": c.agent_id,
                                                     "message": content, "requester": agent_requester(who)})
            except AgentUnavailable:
                yield self._agent_down(c)
                yield c.event("done")
                return
            for ev in self._state_events(c, who, state):
                yield ev
            yield c.event("done")

    # ---------- 실행 승인 ----------
    def claim_approval(self, approval_id: str, who: Requester, decision: str) -> tuple[Approval, Conversation]:
        """확인하고 바로 결정을 적어 둡니다. 사이에 await가 없어 같은 승인을 두 번 결정하지 못합니다."""
        ap = self.approvals.get(approval_id)
        if ap is None:
            raise ProblemError(404, "not-found", "실행 승인이 없습니다")
        if ap.owner != who.id:
            raise ProblemError(403, "forbidden", "요청한 직원만 결정합니다")
        c = self.conversations[ap.conversation_id]
        if ap.decided or c.pending != ap.id:
            raise ProblemError(409, "invalid-state", "이미 결정했거나 기다리는 승인이 아닙니다")
        if now() > ap.expires_at:
            raise ProblemError(409, "invalid-state", "승인 시간이 지났습니다. 다시 요청해 주세요")
        ap.decided = decision
        return ap, c

    async def decision_events(self, ap: Approval, c: Conversation, who: Requester, decision: str,
                              comment: str | None) -> AsyncIterator[dict[str, Any]]:
        async with c.lock:
            yield c.event("approval_decided", decision={"approvalId": ap.id, "decision": decision})
            self.audit.event("execution_approval.decided", employee_id=who.id, agent_id=c.agent_id,
                             via_token=False, result="ok", conversation_id=c.id,
                             detail=f"approval={ap.id} decision={decision}")
            body = {"conversationId": c.id, "approvalId": ap.id, "decision": decision}
            if comment:
                body["comment"] = comment
            try:
                r = await self.agent.resume(self._token(who, c), body)
            except AgentUnavailable:
                ap.decided = None  # agent에 닿지 않았으면 다시 결정할 수 있게 둡니다
                yield self._agent_down(c)
                yield c.event("done")
                return
            if r.status_code == 409:
                c.status, c.pending = "active", None
                yield c.event("error", error={"message": "에이전트가 이 승인을 기다리고 있지 않습니다",
                                              "retryable": False})
            elif r.status_code != 200:
                ap.decided = None
                yield self._agent_down(c)
            else:
                for ev in self._state_events(c, who, r.json()):
                    yield ev
            yield c.event("done")


def stream(events: AsyncIterator[dict[str, Any]]) -> StreamingResponse:
    async def body() -> AsyncIterator[bytes]:
        async for ev in events:
            yield sse(ev)
    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def build_router(chat: ChatService) -> APIRouter:
    api = APIRouter()

    async def requester(request: Request) -> Requester:
        return await load_requester(chat.erp, bearer(request))

    async def json_body(request: Request) -> dict[str, Any]:
        raw = await request.body()
        if not raw:
            return {}
        try:
            body = json.loads(raw)
        except ValueError:
            raise ProblemError(422, "validation", "JSON 본문이 아닙니다")
        if not isinstance(body, dict):
            raise ProblemError(422, "validation", "JSON 객체가 필요합니다")
        return body

    @api.get("/agents")
    async def list_agents(request: Request) -> JSONResponse:
        who = await requester(request)
        items = [{"id": a.id, "name": a.name, "description": a.description,
                  "modelPolicy": a.model_policy.get("mode", "local_only"),
                  "callable": grant_matches(a.callable_by, who)} for a in chat.registry.all()]
        return JSONResponse({"items": [a for a in items if a["callable"]]})

    @api.get("/conversations")
    async def list_conversations(request: Request) -> JSONResponse:
        who = await requester(request)
        mine = sorted((c for c in chat.conversations.values() if c.owner == who.id),
                      key=lambda c: c.updated_at or c.created_at, reverse=True)
        return JSONResponse({"items": [chat.summary(c) for c in mine]})

    @api.post("/conversations", status_code=201)
    async def create_conversation(request: Request) -> JSONResponse:
        who = await requester(request)
        body = await json_body(request)
        if set(body) - {"agentId"}:
            raise ProblemError(422, "validation", "agentId만 받습니다")
        agent_id = body.get("agentId")
        if agent_id is not None:
            agent = chat.registry.get(agent_id)
            if agent is None or not grant_matches(agent.callable_by, who):
                raise ProblemError(403, "forbidden", "이 에이전트를 부를 수 없습니다", str(agent_id))
        c = Conversation(id="conv_" + uuid.uuid4().hex, owner=who.id, created_at=now(), agent_id=agent_id)
        chat.conversations[c.id] = c
        return JSONResponse(chat.summary(c), status_code=201)

    @api.get("/conversations/{conversation_id}")
    async def get_conversation(request: Request, conversation_id: str) -> JSONResponse:
        c = chat.owned(conversation_id, await requester(request))
        return JSONResponse({**chat.summary(c), "events": c.events})

    @api.post("/conversations/{conversation_id}/messages")
    async def post_message(request: Request, conversation_id: str) -> StreamingResponse:
        who = await requester(request)
        c = chat.owned(conversation_id, who)
        body = await json_body(request)
        content = body.get("content")
        if not isinstance(content, str) or not content.strip() or len(content) > MAX_CONTENT or set(body) - {"content"}:
            raise ProblemError(422, "validation", f"content는 1~{MAX_CONTENT}자 문자열이어야 합니다")
        if c.status == "awaiting_approval":
            raise ProblemError(409, "invalid-state", "실행 승인을 기다리는 중입니다")
        return stream(chat.message_events(c, who, content))

    @api.post("/execution-approvals/{approval_id}")
    async def decide(request: Request, approval_id: str) -> StreamingResponse:
        who = await requester(request)
        body = await json_body(request)
        decision, comment = body.get("decision"), body.get("comment")
        if decision not in ("approve", "reject") or set(body) - {"decision", "comment"} or (
                comment is not None and (not isinstance(comment, str) or len(comment) > 200)):
            raise ProblemError(422, "validation", "decision은 approve·reject, comment는 200자 이하입니다")
        ap, c = chat.claim_approval(approval_id, who, decision)
        return stream(chat.decision_events(ap, c, who, decision, comment))

    return api
