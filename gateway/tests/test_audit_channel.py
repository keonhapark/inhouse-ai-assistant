"""gateway 감사 이벤트의 actor.channel(#338, 계약 #339): 직원 JWT는 web, 슬랙 로그인 토큰은 slack, 위임 토큰은 agent."""

import json

import httpx
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from .conftest import ROOT
from .test_chat import FakeAgent, _login, _new, events
from .test_egress import MSG, _agent_ids, token_for  # noqa: F401  (픽스처)
from .test_slack_login import _app, _login as _slack_login, auditor, emp, users_file  # noqa: F401  (픽스처)

SCHEMA = Draft202012Validator(json.loads((ROOT / "contracts/events/audit.schema.json").read_text(encoding="utf-8")))


def _events(app):
    evs = app.state.audit.events.read_all()
    for e in evs:
        SCHEMA.validate(e)
    return evs


def _chat_app(settings, issuer, users_file, agent):
    return _app(settings, issuer, users_file, agent_transport=httpx.MockTransport(agent))


def test_web_and_slack_chat_events_are_marked(settings, issuer, users_file, emp):
    agent = FakeAgent()
    app = _chat_app(settings, issuer, users_file, agent)
    with TestClient(app) as c:
        web = _login(c, emp["employee_no"])
        slack = {"Authorization": f"Bearer {_slack_login(c).json()['accessToken']}"}
        for h, text in ((web, "출장비 규정 알려 줘"), (slack, "회의실 예약해 줘")):
            cid = _new(c, h, agentId="assistant")   # explicit → gateway가 route.decided를 남김
            ev = events(c.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": text}))
            if text.startswith("회의실"):
                ap = next(e for e in ev if e["type"] == "approval_required")["approval"]["approvalId"]
                events(c.post(f"/api/execution-approvals/{ap}", headers=h, json={"decision": "approve"}))
        evs = _events(app)
        by = {}
        for e in evs:
            by.setdefault(e["kind"], set()).add(e["actor"].get("channel"))
        assert by["auth.login"] == {"slack"}                                   # gateway는 슬랙 로그인만 남김
        assert by["route.decided"] == {"web", "slack"}
        assert by["auth.delegation_token_issued"] == {"web", "slack"}
        assert by["execution_approval.requested"] == {"slack"}
        assert by["execution_approval.decided"] == {"slack"}


def test_egress_events_are_agent_with_token_and_unknown_without(client, app, token_for, litellm):
    _, external_ok = _agent_ids(app)
    client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                json={"model": "external", "messages": MSG})
    client.post("/v1/chat/completions", json={"model": "local", "messages": MSG})
    with_token, without = [e for e in _events(app) if e["kind"] == "llm.request"][-2:]
    assert with_token["actor"]["channel"] == "agent"
    assert "channel" not in without["actor"]     # 토큰 없는 호출(입구 라우터 등)은 입구를 모름


def test_requester_channel_from_token():
    import jwt

    from gateway.delegation import channel_of

    assert channel_of(jwt.encode({"sub": "E1"}, "k" * 32, algorithm="HS256")) == "web"
    assert channel_of(jwt.encode({"sub": "E1", "amr": ["slack"]}, "k" * 32, algorithm="HS256")) == "slack"
