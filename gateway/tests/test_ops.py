"""관리자 콘솔 조회 /api/ops/egress(#211). 가림 뒤 본문과 가린 자리만, auditor만."""

import importlib.util

import pytest

from .conftest import ROOT, _employees

_spec = importlib.util.spec_from_file_location("ops_schema_check", ROOT / "contracts/tests/schema_check.py")
schema_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(schema_check)


@pytest.fixture
def auditor(client):
    no = next(e["employee_no"] for e in _employees() if e["unit_id"] == "it-ops")
    tok = client.post("/api/auth/login", json={"employeeNo": no, "password": "demo-pass"}).json()["accessToken"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def ext(app, login, issue, staff_no):
    agent = next(a.id for a in app.state.registry.all() if a.model_policy["mode"] == "external_allowed")
    return agent, issue(login(staff_no), agent, "conv-ops").token


def _send(client, token, messages):
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token},
                    json={"model": "external", "messages": messages})
    assert r.status_code == 200


def js_slice(text: str, start: int, end: int) -> str:
    """UTF-16 위치로 자르기(JavaScript String.prototype.slice와 같음)."""
    b = text.encode("utf-16-le")
    return b[start * 2:end * 2].decode("utf-16-le")


def test_egress_records_have_redacted_text_and_utf16_positions(client, auditor, ext, staff_no):
    agent, token = ext
    _send(client, token, [{"role": "user", "content": "😀 연락처 010-1234-5678"},
                          {"role": "user", "content": [{"type": "text", "text": "a"},
                                                       {"type": "text", "text": "메일 hong@example.com"}]}])
    r = client.get("/api/ops/egress", headers=auditor)
    assert r.status_code == 200
    (item,) = r.json()["items"]
    schema_check.validate("openapi/gateway.yaml", "EgressRecord", item)
    assert item["agentId"] == agent and item["actorId"] == staff_no and item["conversationId"] == "conv-ops"
    assert item["model"] == "anthropic/claude-haiku-5-5" and item["agentName"]
    assert "010-1234-5678" not in str(item) and "hong@example.com" not in str(item)
    assert item["messages"][1]["content"] == "a\n메일 [이메일]"
    for red in item["redactions"]:
        content = item["messages"][red["messageIndex"]]["content"]
        assert js_slice(content, red["start"], red["end"]) == red["placeholder"]
    assert {r["entity"] for r in item["redactions"]} == {"KR_PHONE", "EMAIL_ADDRESS"}


def test_egress_filters_and_cursor(client, auditor, ext):
    agent, token = ext
    for i in range(5):
        _send(client, token, [{"role": "user", "content": f"질문 {i}"}])
    seen, cursor = [], None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = client.get("/api/ops/egress", headers=auditor, params=params).json()
        seen += [i["recordId"] for i in body["items"]]
        cursor = body["nextCursor"]
        if not cursor:
            break
    everything = client.get("/api/ops/egress", headers=auditor).json()["items"]
    assert seen == [i["recordId"] for i in everything] and len(seen) == 5
    assert [i["messages"][0]["content"] for i in everything] == [f"질문 {i}" for i in range(4, -1, -1)]  # 최근 것부터
    assert client.get("/api/ops/egress", headers=auditor, params={"agentId": "nobody"}).json()["items"] == []
    assert client.get("/api/ops/egress", headers=auditor,
                      params={"until": "2000-01-01T00:00:00+09:00"}).json()["items"] == []


def test_egress_access(client, auditor, ext, login, staff_no):
    _, token = ext
    assert client.get("/api/ops/egress", headers={"Authorization": f"Bearer {login(staff_no)}"}).status_code == 403
    assert client.get("/api/ops/egress", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.get("/api/ops/egress").status_code == 401
    assert client.get("/api/ops/egress", headers=auditor, params={"cursor": "@@"}).status_code == 400
    assert client.get("/api/ops/egress", headers=auditor, params={"since": "2026-11-20T10:00:00"}).status_code == 400
