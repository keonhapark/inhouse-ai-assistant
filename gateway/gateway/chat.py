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
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from gateway.audit import AuditLog
from gateway.delegation import DelegationService, load_requester
from gateway.egress import ModelUsage
from gateway.erp_client import ErpClient
from gateway.vision import clean_data_url
from gateway.problems import ProblemError
from gateway.registry import Registry, Requester, grant_matches
from gateway.relay import bearer

log = logging.getLogger(__name__)

APPROVAL_TTL = timedelta(minutes=10)
WIDE_TOKEN_CONDITIONS = ("no_guard", "baseline_tools")  # contracts/eval/conditions.md 위임 토큰 범위
EVAL_CONDITIONS = ("no_guard", "write_blocked", "approve_all", "baseline_tools", "full")  # agent.yaml Condition
# X-Eval-Model-Override 값(contracts/openapi/gateway.yaml createConversation, #346) → 위치별 바꿔 끼울 별칭
EVAL_MODEL_OVERRIDES = {
    "local=local-exaone": {"local": "local-exaone"},
    "external=external-sonnet": {"external": "external-sonnet"},
    "local=local-exaone,external=external-sonnet": {"local": "local-exaone", "external": "external-sonnet"},
    "external=external-exaone": {"external": "external-exaone"},   # K-EXAONE 2.5 API(#436)
    "local=local-gemma4": {"local": "local-gemma4"},               # Gemma 4 12B(#595, 결정 0009)
}
MAX_CONTENT = 4000
AWAITING_CONFIRM = "실행 전 확인이 남아 있습니다. 확인 카드에서 먼저 결정하세요."
BLOCKED_DEFAULT = "회사 정책상 처리할 수 없는 요청입니다. 다른 방법으로 요청하거나 담당 부서에 문의하세요."


def agent_label(name: str) -> str:
    """대화 안에서 부르는 AI 에이전트 이름(ux/copy-guide.md 1.2). 부서 이름이면 "○○ 담당 AI", "비서"·"AI"로 끝나면 그대로."""
    return name if name.endswith(("비서", "AI")) else f"{name} 담당 AI"
MAX_ATTACHMENTS = 3  # contracts/openapi/gateway.yaml postMessage attachments maxItems


def check_attachments(value: Any) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """대화 첨부(#288)를 LLM 출구 이미지 입력(#261)과 같은 규칙으로 확인합니다(413·415·422).

    (agent에 넘길 본문, 대화 기록에 남길 메타(AttachmentMeta, #395))를 돌려줍니다. agent에 넘길 이미지는 다시 인코딩해
    EXIF 같은 메타데이터를 지운 것이고(#458), 메타의 크기·해시도 그 이미지 기준입니다(출구 감사의 해시와 같음).
    메타에는 이미지 본문이 없습니다.
    """
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_ATTACHMENTS:
        raise ProblemError(422, "validation", f"사진은 한 번에 {MAX_ATTACHMENTS}장까지 첨부할 수 있습니다.")
    clean: list[dict[str, str]] = []
    metas: list[dict[str, Any]] = []
    for i, a in enumerate(value, 1):
        if not isinstance(a, dict) or set(a) != {"kind", "dataUrl"} or a["kind"] != "image" \
                or not isinstance(a["dataUrl"], str):
            raise ProblemError(422, "validation", "첨부는 {kind: image, dataUrl}만 받습니다", f"{i}번째 첨부")
        url, info = clean_data_url(a["dataUrl"], i)
        clean.append({"kind": "image", "dataUrl": url})
        metas.append({"kind": "image", "mediaType": info.mime, "bytes": info.size, "sha256": info.sha256})
    return clean, metas


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
    condition: str | None = None   # 평가 조건(X-Eval-Condition). 운영에서는 None
    unit_id: str | None = None     # 요청자 소속 부서(비용 상한의 부서 기준)
    model_override: dict[str, str] = field(default_factory=dict)  # 평가 별칭 바꿔 끼우기(#346). 운영에서는 빈 dict
    route_method: str | None = None  # 대화를 연 라우팅 방식(llm·keyword·fallback·explicit). /run의 routeMethod(#311)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def event(self, type_: str, **fields: Any) -> dict[str, Any]:
        t = now()
        ev = {"type": type_, "conversationId": self.id, "seq": self.seq, "at": iso(t), **fields}
        self.seq += 1
        self.events.append(ev)
        self.updated_at = t
        return ev


def done(c: Conversation, model: dict[str, str] | None) -> dict[str, Any]:
    """마지막 이벤트. 이 차례에서 출구가 실제로 쓴 모델이 있으면 model(name, location)을 붙입니다."""
    return c.event("done", **({"model": model} if model else {}))


def sse(ev: dict[str, Any]) -> bytes:
    return f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n".encode()


def agent_requester(who: Requester) -> dict[str, Any]:
    return {"employeeId": who.id, "unitId": who.unit_id, "grade": who.grade, "roles": list(who.roles)}


class ChatService:
    def __init__(self, erp: ErpClient, registry: Registry, delegation: DelegationService, agent: AgentClient,
                 audit: AuditLog, eval_mode: bool = False, usage: ModelUsage | None = None):
        self.usage = usage or ModelUsage()
        self.eval_mode = eval_mode
        self.erp, self.registry, self.delegation, self.agent, self.audit = erp, registry, delegation, agent, audit
        self.conversations: dict[str, Conversation] = {}
        self.approvals: dict[str, Approval] = {}

    # ---------- 조회 ----------
    def summary(self, c: Conversation) -> dict[str, Any]:
        agent = self.registry.get(c.agent_id) if c.agent_id else None
        return {"conversationId": c.id, "agentId": c.agent_id, "agentName": agent.name if agent else None,
                "title": c.title, "status": c.status, "createdAt": iso(c.created_at),
                "updatedAt": iso(c.updated_at or c.created_at)}

    def condition_of(self, conversation_id: str | None) -> str | None:
        c = self.conversations.get(conversation_id or "")
        return c.condition if c else None

    def model_override_of(self, conversation_id: str | None) -> dict[str, str]:
        c = self.conversations.get(conversation_id or "")
        return c.model_override if c else {}

    def unit_of(self, conversation_id: str | None) -> str | None:
        c = self.conversations.get(conversation_id or "")
        return c.unit_id if c else None

    def owned(self, conversation_id: str, who: Requester) -> Conversation:
        c = self.conversations.get(conversation_id)
        if c is None or c.owner != who.id:
            raise ProblemError(404, "not-found", "대화가 없습니다")
        return c

    # ---------- 이벤트 만들기 ----------
    def _token(self, who: Requester, c: Conversation) -> str:
        c.unit_id = who.unit_id
        issued = self.delegation.issue_for(who, c.agent_id, c.id, wide=c.condition in WIDE_TOKEN_CONDITIONS)
        self.audit.event("auth.delegation_token_issued", employee_id=who.id, channel=who.channel, agent_id=c.agent_id, via_token=False,
                         result="ok", conversation_id=c.id, detail=f"jti={issued.claims['jti']}")
        return issued.token

    @staticmethod
    def _valid_state(state: Any) -> bool:
        """RunState에서 gateway가 쓰는 필드만 봅니다. 틀리면 상태를 바꾸기 전에 거릅니다."""
        try:
            assert isinstance(state, dict)
            for a in state.get("actions") or []:
                assert all(k in a for k in ("actionId", "tool", "summary", "undoable"))
            for m in state.get("messages") or []:
                assert isinstance(m.get("content"), str)
            if state.get("status") == "awaiting_approval":
                tp = state["pendingApproval"]["toolPreview"]
                assert isinstance(state["pendingApproval"]["approvalId"], str)
                assert all(k in tp for k in ("tool", "risk", "preview"))
            return True
        except (AssertionError, AttributeError, KeyError, TypeError):
            return False

    def _state_events(self, c: Conversation, who: Requester, state: dict[str, Any],
                      model: dict[str, str] | None = None) -> list[dict[str, Any]]:
        if not self._valid_state(state):
            return [c.event("error", error={"message": "AI 에이전트의 답을 읽지 못했습니다. 다시 보내 주세요.",
                                            "retryable": False})]
        out = []
        for a in state.get("actions") or []:
            out.append(c.event("action", action={k: a[k] for k in ("actionId", "tool", "summary", "undoable")}))
        for m in state.get("messages") or []:
            out.append(c.event("message", text=m["content"], **({"model": model} if model else {})))
        if state.get("citations"):
            out.append(c.event("citations", citations=state["citations"]))
        status = state.get("status")
        pending = state.get("pendingApproval")
        if status == "awaiting_approval" and pending:
            tp = pending["toolPreview"]
            ap = Approval(pending["approvalId"], c.id, who.id, tp["tool"], now() + APPROVAL_TTL)
            self.approvals[ap.id] = ap
            c.status, c.pending = "awaiting_approval", ap.id
            approval = {"approvalId": ap.id, "tool": tp["tool"], "risk": tp["risk"], "preview": tp["preview"],
                        "expiresAt": iso(ap.expires_at)}
            if isinstance(tp.get("fromAttachments"), bool):
                # 이 턴에 agent가 첨부 이미지를 읽었는지(결정 0004). 화면이 "확인 필요"를 표시합니다(#395)
                approval["fromAttachments"] = tp["fromAttachments"]
            out.append(c.event("approval_required", approval=approval))
            self.audit.event("execution_approval.requested", employee_id=who.id, channel=who.channel, agent_id=c.agent_id,
                             via_token=False, result="pending", conversation_id=c.id, detail=f"approval={ap.id}")
        else:
            c.status, c.pending = "active", None
        if status == "blocked":
            out.append(c.event("blocked", blocked={"reason": state.get("blockedReason") or BLOCKED_DEFAULT,
                                                   "code": "policy_denied"}))
        elif status == "failed":
            out.append(c.event("error", error={"message": "AI 에이전트가 요청을 끝내지 못했습니다. 다시 보내 주세요.",
                                               "retryable": False}))
        return out

    def _agent_down(self, c: Conversation) -> dict[str, Any]:
        return c.event("error", error={"message": "AI 에이전트가 답하지 않았습니다. 잠시 뒤 다시 보내 주세요.",
                                       "retryable": True})

    # ---------- 메시지 ----------
    async def message_events(self, c: Conversation, who: Requester, content: str,
                             attachments: list[dict[str, str]] | None = None,
                             metas: list[dict[str, Any]] | None = None) -> AsyncIterator[dict[str, Any]]:
        async with c.lock:
            if c.status == "awaiting_approval":
                ap = self.approvals.get(c.pending or "")
                if ap is None or ap.decided or now() <= ap.expires_at:
                    # 앞 메시지가 승인 대기로 끝났으면 이 메시지는 받지 않습니다
                    yield c.event("error", error={"message": AWAITING_CONFIRM, "retryable": False})
                    yield c.event("done")
                    return
                # 시간이 지난 승인은 거절로 처리해 agent의 대기를 풀고 새 메시지를 이어 갑니다.
                for ev in await self._expire(ap, c, who):
                    yield ev
            c.events.append({"type": "user_message", "content": content, "at": iso(now()),
                             **({"attachments": metas} if metas else {})})
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
                        yield c.event("error", error={"message": "요청을 맡을 AI 에이전트를 찾지 못했습니다. "
                                                                 "AI 에이전트를 직접 골라 다시 보내세요.",
                                                      "retryable": False})
                        yield c.event("done")
                        return
                    route = {"agentId": agent.id, "agentName": agent.name, "method": d.get("method", "llm"),
                             "reason": d.get("reason", ""), "suggestedAgentId": d.get("suggestedAgentId")}
                else:
                    agent = self.registry.get(c.agent_id)
                    route = {"agentId": agent.id, "agentName": agent.name, "method": "explicit",
                             "reason": "직접 골랐습니다", "suggestedAgentId": None}
                if not grant_matches(agent.callable_by, who):
                    # 운영 지표의 차단 수(agent_not_callable)에 들어가도록 거절한 라우팅도 감사 이벤트로 남깁니다.
                    self.audit.event("route.decided", employee_id=who.id, channel=who.channel, agent_id=agent.id, via_token=False,
                                     result="denied", conversation_id=c.id,
                                     problem_type="urn:problem:agent-not-callable",
                                     routing={"agentId": agent.id, "method": route["method"],
                                              "reason": "요청자가 부를 수 없는 에이전트"})
                    yield c.event("blocked", blocked={"reason": f"{agent_label(agent.name)}는 사용할 권한이 없습니다. "
                                                                "다른 AI 에이전트를 고르세요.",
                                                      "code": "agent_not_callable"})
                    yield c.event("done")
                    return
                c.agent_id, c.routed, c.route_method = agent.id, True, route["method"]
                if route["method"] == "explicit":
                    # 직원이 고른 대화는 agent 라우터를 거치지 않아 gateway가 route.decided를 남깁니다(운영 지표 호출 수).
                    self.audit.event("route.decided", employee_id=who.id, channel=who.channel, agent_id=agent.id, via_token=False,
                                     result="ok", conversation_id=c.id,
                                     routing={"agentId": agent.id, "method": "explicit", "reason": route["reason"]})
                yield c.event("route", route=route)

            token = self._token(who, c)
            try:
                body = {"conversationId": c.id, "agentId": c.agent_id, "message": content,
                        "requester": agent_requester(who)}
                if c.condition:
                    body["condition"] = c.condition
                if c.route_method:
                    # fallback이면 agent가 그 대화를 로컬로만 실행합니다(#308: 로컬 장애 때 외부 허용 fallback 에이전트로 넘어가 외부로 나가던 경로).
                    # 계약은 첫 턴만 넘겨도 된다고 하지만, agent가 다시 떠도 같게 매 턴 넘깁니다.
                    body["routeMethod"] = c.route_method
                if attachments:
                    # 이 턴의 첨부만 넘깁니다. 대화 기록(c.events)에는 남기지 않습니다(화면 복원은 글만)
                    body["attachments"] = attachments
                self.usage.begin(c.id)
                state = await self.agent.run(token, body)
            except AgentUnavailable:
                self.usage.take(c.id)
                yield self._agent_down(c)
                yield c.event("done")
                return
            model = self.usage.take(c.id)
            for ev in self._state_events(c, who, state, model):
                yield ev
            yield done(c, model)

    async def _expire(self, ap: Approval, c: Conversation, who: Requester) -> list[dict[str, Any]]:
        ap.decided = "reject"
        out = [c.event("approval_decided", decision={"approvalId": ap.id, "decision": "reject"})]
        self.audit.event("execution_approval.decided", employee_id=who.id, channel=who.channel, agent_id=c.agent_id, via_token=False,
                         result="ok", conversation_id=c.id, detail=f"approval={ap.id} decision=reject(expired)")
        try:
            await self.agent.resume(self._token(who, c), {"conversationId": c.id, "approvalId": ap.id,
                                                           "decision": "reject", "comment": "승인 시간 초과"})
        except AgentUnavailable:
            pass  # 이어지는 /run도 agent에 닿지 않으면 error로 끝납니다
        c.status, c.pending = "active", None
        return out

    def expired_pending(self, c: Conversation) -> bool:
        ap = self.approvals.get(c.pending or "")
        return ap is not None and not ap.decided and now() > ap.expires_at

    # ---------- 실행 승인 ----------
    def claim_approval(self, approval_id: str, who: Requester, decision: str) -> tuple[Approval, Conversation]:
        """확인하고 바로 결정을 적어 둡니다. 사이에 await가 없어 같은 승인을 두 번 결정하지 못합니다."""
        ap = self.approvals.get(approval_id)
        if ap is None:
            raise ProblemError(404, "not-found", "확인할 실행이 없습니다.")
        if ap.owner != who.id:
            raise ProblemError(403, "forbidden", "요청한 사람만 확인할 수 있습니다.")
        c = self.conversations[ap.conversation_id]
        if ap.decided or c.pending != ap.id:
            raise ProblemError(409, "invalid-state", "이미 처리한 실행 전 확인입니다.")
        if now() > ap.expires_at:
            raise ProblemError(409, "invalid-state", "확인 시간이 지났습니다.",
                               "이 실행은 하지 않았습니다. 다시 하려면 새 메시지를 보내세요.")
        ap.decided = decision
        return ap, c

    async def decision_events(self, ap: Approval, c: Conversation, who: Requester, decision: str,
                              comment: str | None) -> AsyncIterator[dict[str, Any]]:
        async with c.lock:
            yield c.event("approval_decided", decision={"approvalId": ap.id, "decision": decision})
            self.audit.event("execution_approval.decided", employee_id=who.id, channel=who.channel, agent_id=c.agent_id,
                             via_token=False, result="ok", conversation_id=c.id,
                             detail=f"approval={ap.id} decision={decision}")
            body = {"conversationId": c.id, "approvalId": ap.id, "decision": decision}
            if comment:
                body["comment"] = comment
            try:
                self.usage.begin(c.id)
                r = await self.agent.resume(self._token(who, c), body)
            except AgentUnavailable:
                self.usage.take(c.id)
                ap.decided = None  # agent에 닿지 않았으면 다시 결정할 수 있게 둡니다
                yield self._agent_down(c)
                yield c.event("done")
                return
            model = self.usage.take(c.id)
            if r.status_code == 409:
                c.status, c.pending = "active", None
                yield c.event("error", error={"message": "이미 끝난 실행 전 확인입니다. 새 메시지를 보내세요.",
                                              "retryable": False})
            elif r.status_code != 200:
                ap.decided = None
                yield self._agent_down(c)
            else:
                try:
                    state = r.json()
                except ValueError:
                    state = None
                if not self._valid_state(state):
                    ap.decided = None
                for ev in self._state_events(c, who, state, model):
                    yield ev
            yield done(c, model)


_running: set[asyncio.Task] = set()


def stream(c: Conversation, events: AsyncIterator[dict[str, Any]],
           on_fail: Callable[[], None] | None = None) -> StreamingResponse:
    """이벤트 생성을 응답 스트림과 떼어 따로 끝까지 돌립니다.

    화면이 연결을 끊어도 agent 호출과 대화 상태(승인 대기, 결정) 반영은 끝까지 갑니다. 끊긴 뒤의 이벤트는
    대화 기록(GET /conversations/{id})에서 봅니다. 생성 중 예외가 나면 on_fail로 상태를 되돌리고 error·done을 보냅니다.
    """
    q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def produce() -> None:
        try:
            async for ev in events:
                q.put_nowait(ev)
        except Exception as e:
            log.exception("대화 처리 중 오류 conversation=%s", c.id)
            if on_fail:
                on_fail()
            message = e.title if isinstance(e, ProblemError) else "메시지를 처리하지 못했습니다. 다시 보내 주세요."
            q.put_nowait(c.event("error", error={"message": message, "retryable": False}))
            q.put_nowait(c.event("done"))
        finally:
            q.put_nowait(None)

    task = asyncio.create_task(produce())
    _running.add(task)
    task.add_done_callback(_running.discard)

    async def body() -> AsyncIterator[bytes]:
        while (ev := await q.get()) is not None:
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

    @api.get("/agent-registry")
    async def agent_registry(request: Request) -> JSONResponse:
        """부를 수 없는 에이전트까지 모두 보여 줍니다. 팩 단계 밖 에이전트는 등록부에 싣지 않았으므로 빠집니다(#170)."""
        who = await requester(request)
        reg = chat.registry
        body: dict[str, Any] = {"items": [reg.registry_entry(a, who) for a in reg.all()]}
        if reg.fallback_agent is not None:
            body["fallbackAgentId"] = reg.fallback_agent
        return JSONResponse(body)

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
        condition = request.headers.get("x-eval-condition")
        if condition is not None:
            if not chat.eval_mode:
                raise ProblemError(400, "validation", "평가 모드가 아니라 X-Eval-Condition을 받지 않습니다")
            if condition not in EVAL_CONDITIONS:
                raise ProblemError(422, "validation", "X-Eval-Condition 값이 올바르지 않습니다",
                                   ", ".join(EVAL_CONDITIONS))
        override = request.headers.get("x-eval-model-override")
        if override is not None:
            if not chat.eval_mode:
                raise ProblemError(400, "validation", "평가 모드가 아니라 X-Eval-Model-Override를 받지 않습니다")
            if override not in EVAL_MODEL_OVERRIDES:
                raise ProblemError(422, "validation", "X-Eval-Model-Override 값이 올바르지 않습니다",
                                   ", ".join(EVAL_MODEL_OVERRIDES))
        agent_id = body.get("agentId")
        if agent_id is not None:
            agent = chat.registry.get(agent_id)
            if agent is None or not grant_matches(agent.callable_by, who):
                raise ProblemError(403, "forbidden", "이 AI 에이전트를 사용할 권한이 없습니다.", "다른 AI 에이전트를 고르세요.")
        c = Conversation(id="conv_" + uuid.uuid4().hex, owner=who.id, created_at=now(), agent_id=agent_id,
                         condition=condition, model_override=dict(EVAL_MODEL_OVERRIDES.get(override or "", {})))
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
        if isinstance(content, str) and len(content) > MAX_CONTENT:
            raise ProblemError(422, "validation", f"메시지는 {MAX_CONTENT:,}자까지 보낼 수 있습니다.",
                               "줄여서 다시 보내세요.")
        if not isinstance(content, str) or not content.strip() or set(body) - {"content", "attachments"}:
            raise ProblemError(422, "validation", "보낼 메시지가 없습니다.", "내용을 쓰고 다시 보내세요.")
        attachments, metas = check_attachments(body["attachments"]) if "attachments" in body else (None, None)
        if c.status == "awaiting_approval" and not chat.expired_pending(c):
            raise ProblemError(409, "invalid-state", "실행 전 확인이 남아 있습니다.", "확인 카드에서 먼저 결정하세요.")
        return stream(c, chat.message_events(c, who, content, attachments, metas))

    @api.post("/execution-approvals/{approval_id}")
    async def decide(request: Request, approval_id: str) -> StreamingResponse:
        who = await requester(request)
        body = await json_body(request)
        decision, comment = body.get("decision"), body.get("comment")
        if comment is not None and isinstance(comment, str) and len(comment) > 200:
            raise ProblemError(422, "validation", "의견은 200자까지 쓸 수 있습니다.")
        if decision not in ("approve", "reject") or set(body) - {"decision", "comment"} or (
                comment is not None and not isinstance(comment, str)):
            # 화면 코드가 만드는 값이라 직원이 일으킬 수 없는 오류입니다(개발자용).
            raise ProblemError(422, "validation", "decision은 approve·reject, comment는 문자열입니다")
        ap, c = chat.claim_approval(approval_id, who, decision)

        def release() -> None:
            if c.pending == ap.id:  # agent 결과를 반영하기 전에 실패했으면 다시 결정할 수 있게 둡니다
                ap.decided = None

        return stream(c, chat.decision_events(ap, c, who, decision, comment), on_fail=release)

    return api
