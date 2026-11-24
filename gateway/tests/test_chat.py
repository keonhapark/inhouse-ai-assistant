"""채팅·실행 승인 API. agent는 contracts/openapi/agent.yaml을 따르는 스텁으로 대신합니다."""

import importlib.util
import json

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app

from .conftest import ROOT, _employees

_spec = importlib.util.spec_from_file_location("contract_schema_check", ROOT / "contracts/tests/schema_check.py")
schema_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(schema_check)

PREVIEW = {"dryRun": True, "operation": "createRoomReservation", "summary": "3층 회의실 예약", "changes": [],
           "undoable": True, "warnings": []}


class FakeAgent:
    """agent 계약 스텁. 받은 요청을 모아 두고 RunState를 계약 모양으로 돌려줍니다."""

    def __init__(self):
        self.calls: list[tuple[str, dict, str | None]] = []
        self.route_to = "assistant"
        self.route_method = "keyword"
        self.preview_extra: dict = {}       # toolPreview에 더할 필드(예: fromAttachments)
        self.action_extra: dict = {}        # 완료한 일(ExecutedAction)에 더할 필드(예: toolLabel)
        self.down = False
        self.waiting: dict[str, str] = {}   # approvalId -> conversationId
        self.broken_resume = False          # True면 /resume이 계약에 맞지 않는 RunState를 돌려줌
        self.usage = None                   # gateway ModelUsage. 있으면 /run·/resume에서 출구를 쓴 것처럼 기록
        self.uses: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("down", request=request)
        body = json.loads(request.content)
        token = request.headers.get("x-delegation-token")
        self.calls.append((request.url.path, body, token))
        if request.url.path == "/route":
            return self._ok("RouteDecision", {"agentId": self.route_to, "method": self.route_method, "reason": "키워드 일치",
                                              "confidence": None, "suggestedAgentId": None})
        agent_id = jwt.decode(token, options={"verify_signature": False})["agt"]
        if self.usage is not None:
            for alias, loc in self.uses:
                self.usage.record(body["conversationId"], alias, loc)
        if request.url.path == "/run":
            if "예약" in body["message"]:
                ap = "ap_" + str(len(self.calls))
                self.waiting[ap] = body["conversationId"]
                return self._ok("RunState", {
                    "conversationId": body["conversationId"], "agentId": agent_id, "status": "awaiting_approval",
                    "messages": [{"role": "assistant", "content": "이대로 예약할까요?"}],
                    "pendingApproval": {"approvalId": ap, "toolPreview": {
                        "tool": "room_reserve", "risk": "reversible_write", "arguments": {}, "preview": PREVIEW,
                        **self.preview_extra}}})
            if "막아" in body["message"]:
                return self._ok("RunState", {"conversationId": body["conversationId"], "agentId": agent_id,
                                             "status": "blocked", "messages": [], "blockedReason": "신뢰 등급 위반"})
            return self._ok("RunState", {
                "conversationId": body["conversationId"], "agentId": agent_id, "status": "completed",
                "messages": [{"role": "assistant", "content": "규정은 이렇습니다"}],
                "citations": [{"docId": "d1", "title": "복무 규정", "article": "제3조", "quote": "출장비는", "verified": True}]})
        if request.url.path == "/resume":
            if self.broken_resume:
                return httpx.Response(200, json={"status": "completed", "messages": [{"role": "assistant"}]})
            if self.waiting.pop(body["approvalId"], None) is None:
                return httpx.Response(409, json={"type": "urn:problem:invalid-state", "title": "x", "status": 409})
            if body["decision"] == "reject":
                state = {"status": "completed", "messages": [{"role": "assistant", "content": "취소했습니다"}]}
            else:
                state = {"status": "completed", "messages": [{"role": "assistant", "content": "예약했습니다"}],
                         "actions": [{"tool": "room_reserve", "actionId": "act_1", "summary": "예약함",
                                      "undoable": True, **self.action_extra}]}
            return self._ok("RunState", {"conversationId": body["conversationId"], "agentId": agent_id, **state})
        return httpx.Response(404)

    @staticmethod
    def _ok(schema: str, body: dict) -> httpx.Response:
        schema_check.validate("openapi/agent.yaml", schema, body)
        return httpx.Response(200, json=body)


@pytest.fixture
def agent():
    return FakeAgent()


@pytest.fixture
def chat(settings, fake_erp, issuer, agent):
    app = create_app(settings, erp_transport=httpx.ASGITransport(app=fake_erp), issuer=issuer,
                     llm_transport=httpx.MockTransport(lambda r: httpx.Response(500)),
                     agent_transport=httpx.MockTransport(agent))
    with TestClient(app) as c:
        c.app_ref = app
        yield c


def _login(c, no):
    r = c.post("/api/auth/login", json={"employeeNo": no, "password": "demo-pass"})
    return {"Authorization": f"Bearer {r.json()['accessToken']}"}


def events(r: httpx.Response) -> list[dict]:
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    out = []
    for block in r.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        ev = json.loads(lines["data"])
        assert lines["event"] == ev["type"]
        schema_check.validate("openapi/gateway.yaml", "ChatEvent", ev)
        out.append(ev)
    assert out[-1]["type"] == "done"
    assert [e["seq"] for e in out] == sorted(e["seq"] for e in out)
    return out


@pytest.fixture
def h(chat, staff_no):
    return _login(chat, staff_no)


def _new(chat, h, **body):
    r = chat.post("/api/conversations", headers=h, json=body)
    assert r.status_code == 201, r.text
    schema_check.validate("openapi/gateway.yaml", "ConversationSummary", r.json())
    return r.json()["conversationId"]


def test_agents_lists_callable(chat, h):
    items = chat.get("/api/agents", headers=h).json()["items"]
    for a in items:
        schema_check.validate("openapi/agent.yaml", "AgentInfo", a)
    assert {a["id"] for a in items} == {a.id for a in chat.app_ref.state.registry.all()}


def test_first_message_routes_once_and_runs_with_token(chat, h, agent, staff_no):
    cid = _new(chat, h)
    ev = events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "출장비 규정 알려 줘"}))
    assert [e["type"] for e in ev] == ["route", "message", "citations", "done"]
    assert ev[0]["route"]["agentId"] == "assistant" and ev[0]["route"]["method"] == "keyword"
    path, body, token = agent.calls[-1]
    assert path == "/run" and body["conversationId"] == cid and body["requester"]["employeeId"] == staff_no
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["cid"] == cid and claims["agt"] == "assistant" and claims["sub"] == staff_no
    assert token not in json.dumps(body)            # 토큰은 헤더로만

    ev2 = events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "고마워"}))
    assert "route" not in [e["type"] for e in ev2]
    assert [c[0] for c in agent.calls].count("/route") == 1
    assert ev2[0]["seq"] > ev[-1]["seq"]

    conv = chat.get(f"/api/conversations/{cid}", headers=h).json()
    schema_check.validate("openapi/gateway.yaml", "Conversation", conv)
    assert conv["agentId"] == "assistant" and conv["title"] == "출장비 규정 알려 줘"
    assert [e["type"] for e in conv["events"]].count("user_message") == 2
    assert [c["conversationId"] for c in chat.get("/api/conversations", headers=h).json()["items"]] == [cid]


def test_explicit_agent_skips_router(chat, h, agent):
    cid = _new(chat, h, agentId="hr")
    ev = events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "연차 잔여"}))
    assert ev[0]["route"]["method"] == "explicit" and ev[0]["route"]["agentId"] == "hr"
    assert "/route" not in [c[0] for c in agent.calls]


def test_approval_flow(chat, h, agent):
    cid = _new(chat, h)
    ev = events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "회의실 예약해 줘"}))
    req = next(e for e in ev if e["type"] == "approval_required")["approval"]
    assert req["tool"] == "room_reserve" and req["preview"] == PREVIEW
    assert chat.get(f"/api/conversations/{cid}", headers=h).json()["status"] == "awaiting_approval"

    r = chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "다른 질문"})
    assert r.status_code == 409

    ev = events(chat.post(f"/api/execution-approvals/{req['approvalId']}", headers=h, json={"decision": "approve"}))
    assert [e["type"] for e in ev] == ["approval_decided", "action", "message", "done"]
    assert ev[1]["action"]["actionId"] == "act_1" and ev[1]["action"]["undoable"] is True
    assert agent.calls[-1][1] == {"conversationId": cid, "approvalId": req["approvalId"], "decision": "approve"}
    assert chat.get(f"/api/conversations/{cid}", headers=h).json()["status"] == "active"

    again = chat.post(f"/api/execution-approvals/{req['approvalId']}", headers=h, json={"decision": "approve"})
    assert again.status_code == 409

    kinds = [e["kind"] for e in chat.app_ref.state.audit.events.read_all()]
    assert "execution_approval.requested" in kinds and "execution_approval.decided" in kinds
    assert "auth.delegation_token_issued" in kinds


def test_reject_with_comment(chat, h, agent):
    cid = _new(chat, h)
    ev = events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "회의실 예약"}))
    ap = next(e for e in ev if e["type"] == "approval_required")["approval"]["approvalId"]
    ev = events(chat.post(f"/api/execution-approvals/{ap}", headers=h,
                          json={"decision": "reject", "comment": "시간 바꿀게요"}))
    assert ev[0]["decision"]["decision"] == "reject" and ev[1]["text"] == "취소했습니다"
    assert agent.calls[-1][1]["comment"] == "시간 바꿀게요"


def test_only_requester_decides(chat, h, staff_no):
    cid = _new(chat, h)
    ev = events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "회의실 예약"}))
    ap = next(e for e in ev if e["type"] == "approval_required")["approval"]["approvalId"]
    other = next(e["employee_no"] for e in _employees() if e["employee_no"] != staff_no)
    oh = _login(chat, other)
    assert chat.post(f"/api/execution-approvals/{ap}", headers=oh, json={"decision": "approve"}).status_code == 403
    assert chat.get(f"/api/conversations/{cid}", headers=oh).status_code == 404   # 남의 대화는 없는 것으로
    assert chat.post("/api/execution-approvals/nope", headers=h, json={"decision": "approve"}).status_code == 404


def test_blocked_and_agent_down(chat, h, agent):
    cid = _new(chat, h)
    ev = events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "막아 줘"}))
    assert ev[-2]["type"] == "blocked" and ev[-2]["blocked"]["reason"] == "신뢰 등급 위반"
    agent.down = True
    ev = events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "다시"}))
    assert [e["type"] for e in ev] == ["error", "done"] and ev[0]["error"]["retryable"] is True


def test_routed_agent_not_callable_is_blocked(chat, h, agent):
    from gateway.registry import Registry

    reg = chat.app_ref.state.registry
    raw = [{**a.raw, "callable_by": {"roles": ["nobody"]}} if a.id == "hr" else a.raw for a in reg.all()]
    tools = json.loads((ROOT / "contracts/mcp/tools.json").read_text())
    scopes = json.loads((ROOT / "contracts/auth/scopes.json").read_text())
    new = Registry({"agents": raw}, tools, scopes)
    chat.app_ref.state.chat.registry = new
    chat.app_ref.state.delegation.registry = new
    agent.route_to = "hr"
    cid = _new(chat, h)
    ev = events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "연차"}))
    assert ev[0]["type"] == "blocked" and ev[0]["blocked"]["code"] == "agent_not_callable"
    assert "/run" not in [c[0] for c in agent.calls]
    assert chat.post("/api/conversations", headers=h, json={"agentId": "hr"}).status_code == 403


def test_validation(chat, h):
    cid = _new(chat, h)
    assert chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": ""}).status_code == 422
    assert chat.post(f"/api/conversations/{cid}/messages", headers=h,
                     json={"content": "x" * 4001}).status_code == 422
    assert chat.post("/api/conversations/nope/messages", headers=h, json={"content": "x"}).status_code == 404
    assert chat.post("/api/conversations", headers=h, json={"agentId": "nope"}).status_code == 403
    assert chat.post("/api/execution-approvals/x", headers=h, json={"decision": "maybe"}).status_code == 422
    assert chat.get("/api/conversations").status_code == 401


# ---------- 리뷰에서 고친 것 ----------
def _wait_approval(chat, h):
    cid = _new(chat, h)
    ev = events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "회의실 예약"}))
    return cid, next(e for e in ev if e["type"] == "approval_required")["approval"]["approvalId"]


def test_expired_approval_is_rejected_and_conversation_continues(chat, h, agent):
    from datetime import timedelta

    from gateway.chat import now

    cid, ap = _wait_approval(chat, h)
    chat.app_ref.state.chat.approvals[ap].expires_at = now() - timedelta(seconds=1)
    r = chat.post(f"/api/execution-approvals/{ap}", headers=h, json={"decision": "approve"})
    assert r.status_code == 409
    ev = events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "그냥 규정 알려 줘"}))
    assert ev[0]["type"] == "approval_decided" and ev[0]["decision"]["decision"] == "reject"
    assert "message" in [e["type"] for e in ev]
    resume = next(c for c in agent.calls if c[0] == "/resume")
    assert resume[1]["decision"] == "reject" and resume[1]["approvalId"] == ap
    assert chat.get(f"/api/conversations/{cid}", headers=h).json()["status"] == "active"


def test_malformed_agent_reply_lets_requester_decide_again(chat, h, agent):
    cid, ap = _wait_approval(chat, h)
    agent.broken_resume = True
    ev = events(chat.post(f"/api/execution-approvals/{ap}", headers=h, json={"decision": "approve"}))
    assert [e["type"] for e in ev] == ["approval_decided", "error", "done"]
    assert chat.get(f"/api/conversations/{cid}", headers=h).json()["status"] == "awaiting_approval"
    agent.broken_resume = False
    ev = events(chat.post(f"/api/execution-approvals/{ap}", headers=h, json={"decision": "approve"}))
    assert ev[1]["type"] == "action"


def test_error_mid_stream_still_ends_with_done(chat, h, agent):
    cid = _new(chat, h)
    events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "안녕"}))
    # 라우팅 뒤 에이전트가 등록부에서 빠지면 토큰 발급이 실패합니다(ProblemError).
    chat.app_ref.state.delegation.registry = type("Empty", (), {"get": lambda self, _: None})()
    ev = events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "또"}))
    assert [e["type"] for e in ev] == ["error", "done"]


def test_processing_continues_when_screen_disconnects():
    import asyncio
    from datetime import datetime, timezone

    from gateway.chat import Conversation, stream

    async def go():
        c = Conversation(id="c1", owner="E1", created_at=datetime.now(timezone.utc))

        async def gen():
            await asyncio.sleep(0.01)
            yield c.event("message", text="끝까지 감")
            yield c.event("done")

        stream(c, gen())                  # 응답 본문을 읽지 않음(화면이 끊긴 것과 같음)
        await asyncio.sleep(0.05)
        return [e["type"] for e in c.events]

    assert asyncio.run(go()) == ["message", "done"]


# ---------- 평가 조건(#63) ----------
def test_eval_condition_header(chat, h, agent):
    r = chat.post("/api/conversations", headers={**h, "X-Eval-Condition": "no_guard"}, json={})
    assert r.status_code == 400                                   # 평가 모드가 아님
    chat.app_ref.state.chat.eval_mode = True
    assert chat.post("/api/conversations", headers={**h, "X-Eval-Condition": "maybe"}, json={}).status_code == 422
    cid = chat.post("/api/conversations", headers={**h, "X-Eval-Condition": "write_blocked"}, json={}
                    ).json()["conversationId"]
    events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "규정"}))
    run = [c for c in agent.calls if c[0] == "/run"][-1][1]
    assert run["condition"] == "write_blocked"
    cid2 = _new(chat, h)
    events(chat.post(f"/api/conversations/{cid2}/messages", headers=h, json={"content": "규정"}))
    assert "condition" not in [c for c in agent.calls if c[0] == "/run"][-1][1]


# ---------- 쓴 모델 표시(#121) ----------
def test_message_and_done_carry_model_used(chat, h, agent):
    agent.usage = chat.app_ref.state.egress.usage
    cid = _new(chat, h)
    agent.uses = [("local", "local")]
    ev = events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "규정"}))
    by = {e["type"]: e for e in ev}
    assert by["message"]["model"] == {"name": "local", "location": "local"}
    assert by["done"]["model"] == {"name": "local", "location": "local"}

    agent.uses = [("external", "external"), ("local", "local")]
    ev = events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "또"}))
    assert ev[-1]["model"] == {"name": "external", "location": "external"}

    agent.uses = []
    ev = events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "모델 안 씀"}))
    assert "model" not in ev[-1]


def test_resume_events_carry_model(chat, h, agent):
    agent.usage = chat.app_ref.state.egress.usage
    agent.uses = [("local", "local")]
    cid, ap = _wait_approval(chat, h)
    ev = events(chat.post(f"/api/execution-approvals/{ap}", headers=h, json={"decision": "approve"}))
    assert ev[-1]["model"] == {"name": "local", "location": "local"}
    assert next(e for e in ev if e["type"] == "message")["model"]["location"] == "local"


# ---------- 평가 조건별 장치·토큰 범위(#134) ----------
def _eval_conv(chat, h, condition, agent_id=None):
    chat.app_ref.state.chat.eval_mode = True
    body = {"agentId": agent_id} if agent_id else {}
    return chat.post("/api/conversations", headers={**h, "X-Eval-Condition": condition}, json=body
                     ).json()["conversationId"]


def _token_of_last_run(agent):
    return [c for c in agent.calls if c[0] == "/run"][-1][2]


@pytest.mark.parametrize("condition,wide", [
    ("no_guard", True), ("baseline_tools", True), ("write_blocked", False), ("approve_all", False), ("full", False),
])
def test_token_scope_by_condition(chat, h, agent, condition, wide):
    reg = chat.app_ref.state.registry
    cid = _eval_conv(chat, h, condition, "hr")
    events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "규정"}))
    claims = jwt.decode(_token_of_last_run(agent), options={"verify_signature": False})
    schema_check.validate_file("auth/delegation-token.schema.json", claims)
    scopes = json.loads((ROOT / "contracts/auth/scopes.json").read_text())["scopes"]
    human = {s["id"] for s in scopes if s.get("human_only")}
    assert not set(claims["scopes"]) & human                      # 어느 조건에서도 사람 전용은 없음
    if wide:
        assert set(claims["scopes"]) == {s["id"] for s in scopes} - human
        assert set(claims["doc_scopes"]) == set(reg.all_access_tags)
    else:
        assert set(claims["scopes"]) == set(reg.get("hr").scopes)
        assert set(claims["doc_scopes"]) <= set(reg.get("hr").doc_scopes)
    assert claims["tools"] == list(reg.get("hr").tools)


def test_conversation_remembers_requester_unit_for_budgets(chat, h, staff_no):
    cid = _new(chat, h)
    events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "규정"}))
    unit = next(e["unit_id"] for e in _employees() if e["employee_no"] == staff_no)
    assert chat.app_ref.state.chat.unit_of(cid) == unit
    assert chat.app_ref.state.egress.unit_of(cid) == unit
    assert chat.app_ref.state.chat.unit_of("nope") is None


def test_explicit_route_and_denied_route_are_audited(chat, h):
    cid = _new(chat, h, agentId="hr")
    events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "연차"}))
    ev = [e for e in chat.app_ref.state.audit.events.read_all() if e["kind"] == "route.decided"]
    assert ev[-1]["routing"]["method"] == "explicit" and ev[-1]["result"] == "ok"
    schema_check.validate_file("events/audit.schema.json", ev[-1])
