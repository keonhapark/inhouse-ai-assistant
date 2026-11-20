"""사람용 경로는 위임 토큰을 거절합니다(#159). 실행 승인은 사람 확인 그 자체라 위임 토큰으로 열리면 안 됩니다."""

import pytest

from gateway.registry import Requester

from .test_chat import FakeAgent, agent, chat, h  # noqa: F401  (실행 승인 시험에 채팅 준비를 씀)


@pytest.fixture
def tokens(login, issue, staff_no, app):
    emp = login(staff_no)
    narrow = issue(emp, "hr").token
    reg = app.state.registry
    wide = app.state.issuer.issue(
        Requester(staff_no, "u", "staff", ("employee",), ()),
        reg.get("hr"), "c", scopes=reg.wide_scopes, doc_scopes=reg.all_access_tags).token
    return emp, narrow, wide


ROUTES = [
    ("GET", "/api/me", None),
    ("GET", "/api/agents", None),
    ("GET", "/api/conversations", None),
    ("POST", "/api/conversations", {}),
    ("POST", "/api/conversations/x/messages", {"content": "hi"}),
    ("POST", "/api/execution-approvals/x", {"decision": "approve"}),
    ("GET", "/api/inbox?box=inbox", None),
    ("POST", "/api/inbox/x/approve", {"version": 1}),
    ("GET", "/api/delegations?role=delegator", None),
    ("POST", "/api/delegations", {}),
    ("POST", "/api/actions/x/undo", None),
    ("GET", "/api/notifications", None),
    ("GET", "/api/employees", None),
    ("GET", "/api/approval-forms", None),
    ("GET", "/api/org/units", None),
    ("GET", "/api/agent-registry", None),
    ("GET", "/api/audit-events", None),
]


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_delegation_tokens_are_rejected_on_human_routes(client, tokens, method, path, body):
    _, narrow, wide = tokens
    for t in (narrow, wide):
        r = client.request(method, path, headers={"Authorization": f"Bearer {t}"}, json=body)
        assert r.status_code == 403, (path, r.text)
        assert r.json()["type"] == "urn:problem:delegation-token-not-allowed"


def test_employee_jwt_still_works(client, tokens):
    emp, _, _ = tokens
    assert client.get("/api/me", headers={"Authorization": f"Bearer {emp}"}).status_code == 200
    assert client.post("/api/conversations", headers={"Authorization": f"Bearer {emp}"}, json={}).status_code == 201


def test_execution_approval_cannot_be_decided_with_delegation_token(chat, h, agent):
    """승인 대기를 만든 뒤, 같은 직원의 위임 토큰(agent가 받은 것)으로 승인하려 하면 403이고 결정되지 않습니다."""
    from .test_chat import _wait_approval

    cid, ap = _wait_approval(chat, h)
    agent_token = [c for c in agent.calls if c[0] == "/run"][-1][2]
    r = chat.post(f"/api/execution-approvals/{ap}", headers={"Authorization": f"Bearer {agent_token}"},
                  json={"decision": "approve"})
    assert r.status_code == 403
    assert chat.app_ref.state.chat.approvals[ap].decided is None
    assert chat.get(f"/api/conversations/{cid}", headers=h).json()["status"] == "awaiting_approval"
