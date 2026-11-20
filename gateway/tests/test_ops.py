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


# ---------- /ops/metrics ----------
def _ev(kind, agent, *, result="ok", source="agent", pt=None, method=None, loc=None, trust=None, at="2026-11-20T10:00:00+09:00"):
    import uuid
    e = {"eventId": uuid.uuid4().hex, "occurredAt": at, "source": source, "kind": kind,
         "actor": {"employeeId": "E1", "viaDelegationToken": True, "agentId": agent}, "result": result,
         "problemType": pt}
    if method:
        e["routing"] = {"agentId": agent, "method": method, "reason": "r"}
    if loc:
        e["model"] = {"name": "x", "location": loc, "externalSent": loc == "external", "redactions": 0}
    if trust:
        e["trustLevel"] = trust
    return e


def test_compute_metrics_counts(app):
    from datetime import datetime

    from gateway.budgets import BudgetLedger
    from gateway.ops import compute_metrics

    reg = app.state.registry
    a, b = [x.id for x in reg.all()][:2]
    events = [
        _ev("route.decided", a, method="keyword"), _ev("route.decided", a, method="explicit", source="gateway"),
        _ev("route.decided", b, method="llm"),
        _ev("route.decided", b, result="denied", source="gateway", pt="urn:problem:agent-not-callable", method="llm"),
        _ev("tool.blocked", a, result="denied", pt="urn:problem:agent-policy", trust="untrusted"),
        _ev("tool.blocked", a, result="denied", pt="urn:problem:agent-policy", trust="user_direct"),
        _ev("tool.blocked", a, result="denied", source="mcp", pt="urn:problem:tool-not-allowed"),
        _ev("tool.blocked", a, result="error", source="mcp", pt="urn:problem:validation"),       # 정책 차단 아님
        _ev("rag.access_denied", b, result="denied", source="rag", pt="urn:problem:forbidden"),
        _ev("llm.request", a, source="gateway", loc="local"), _ev("llm.request", a, source="gateway", loc="external"),
        _ev("llm.request", b, result="denied", source="gateway", pt="urn:problem:model-policy", loc="external"),
        _ev("route.decided", a, method="llm", at="2026-11-19T10:00:00+09:00"),                  # 기간 밖
    ]
    egress = [{"occurredAt": "2026-11-20T10:00:01+09:00", "agentId": a, "costUsd": 0.002},
              {"occurredAt": "2026-11-20T10:00:02+09:00", "agentId": a, "costUsd": None}]
    led = BudgetLedger({"period": "month", "agents": {a: 0.001}, "units": {}}, {}, "Asia/Seoul")
    led.add(a, None, 0.002)
    m = compute_metrics(events, egress, reg, led, datetime.fromisoformat("2026-11-20T00:00:00+09:00"),
                        datetime.fromisoformat("2026-11-21T00:00:00+09:00"))
    schema_check.validate("openapi/gateway.yaml", "OpsMetrics", m)
    by = {x["agentId"]: x for x in m["agents"]}
    assert len(m["agents"]) == len(reg.all())
    assert by[a]["calls"] == 2 and by[b]["calls"] == 1
    assert by[a]["blocked"]["byCode"] == {"trust_violation": 1, "policy_denied": 1, "tool_not_allowed": 1}
    assert by[b]["blocked"]["byCode"] == {"agent_not_callable": 1, "scope_missing": 1, "model_policy": 1}
    assert by[a]["llmRequests"] == {"local": 1, "external": 1}
    assert by[a]["externalCostUsd"] == 0.002 and by[a]["unpricedRequests"] == 1
    assert m["routing"] == {"total": 3, "byMethod": {"keyword": 1, "explicit": 1, "llm": 1}}
    assert m["totals"]["blocked"]["total"] == 6 and m["totals"]["calls"] == 3
    (u,) = m["budgets"]["agents"]
    assert u["exceeded"] is True and u["usedUsd"] == 0.002 and m["budgets"]["periodStart"].startswith("20")


def test_ops_metrics_endpoint(client, app, auditor, ext, login, staff_no):
    _, token = ext
    _send(client, token, [{"role": "user", "content": "안녕"}])
    r = client.get("/api/ops/metrics", headers=auditor)
    assert r.status_code == 200
    m = r.json()
    schema_check.validate("openapi/gateway.yaml", "OpsMetrics", m)
    assert m["totals"]["llmRequests"]["external"] >= 1
    assert client.get("/api/ops/metrics", headers={"Authorization": f"Bearer {login(staff_no)}"}).status_code == 403
    assert client.get("/api/ops/metrics", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.get("/api/ops/metrics", headers=auditor, params={"since": "2026-11-21T00:00:00+09:00",
                                                                  "until": "2026-11-20T00:00:00+09:00"}).status_code == 400
